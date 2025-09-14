from flask import Flask, render_template, request, jsonify, redirect, url_for, Response
from flask_cors import CORS
from flask_basicauth import BasicAuth
# from flask_mail import Mail, Message  # Commented out temporarily
import os
from dotenv import load_dotenv
from pymongo import MongoClient
from bson import ObjectId
import traceback

# Explicitly load .env from the same directory as app.py
dotenv_path = os.path.join(os.path.dirname(__file__), '.env')
if os.path.exists(dotenv_path):
    load_dotenv(dotenv_path=dotenv_path)
else:
    print("Warning: .env file not found. App may not work correctly.")

app = Flask(__name__)
CORS(app)

# Email configuration - commented out temporarily
# app.config['MAIL_SERVER'] = 'smtp.gmail.com'
# app.config['MAIL_PORT'] = 587
# app.config['MAIL_USE_TLS'] = True
# app.config['MAIL_USERNAME'] = os.getenv('MAIL_USERNAME')
# app.config['MAIL_PASSWORD'] = os.getenv('MAIL_PASSWORD')
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'your-secret-key-here')

# Basic Auth configuration
app.config['BASIC_AUTH_USERNAME'] = os.getenv('ADMIN_USERNAME', 'admin')
app.config['BASIC_AUTH_PASSWORD'] = os.getenv('ADMIN_PASSWORD', 'password')
basic_auth = BasicAuth(app)

# mail = Mail(app)  # Commented out temporarily

# Multiple admin support: define a custom verifier that checks either
# ADMIN_USERS (CSV of user:pass pairs) or falls back to single-user config.
_admin_users_cache = None

def _load_admin_users():
    global _admin_users_cache
    if _admin_users_cache is not None:
        return _admin_users_cache
    users_env = os.getenv('ADMIN_USERS', '').strip()
    users = {}
    if users_env:
        # Format: "user1:pass1,user2:pass2"
        for pair in users_env.split(','):
            if ':' in pair:
                u, p = pair.split(':', 1)
                u = u.strip()
                p = p.strip()
                if u:
                    users[u] = p
    # Fallback to single admin
    single_user = os.getenv('ADMIN_USERNAME', 'admin')
    single_pass = os.getenv('ADMIN_PASSWORD', 'password')
    if single_user and single_pass and single_user not in users:
        users[single_user] = single_pass
    _admin_users_cache = users
    return _admin_users_cache

@basic_auth.verify_password
def verify_password(username, password):
    users = _load_admin_users()
    expected = users.get(username)
    return expected is not None and password == expected

"""AdSense configuration injected into templates

Environment variables that will be read if present:
- ADSENSE_CLIENT: e.g., "ca-pub-XXXXXXXXXXXXXXXX"
- ADSENSE_SLOT_TOP: optional, numeric slot ID for a header/below-nav ad
- ADSENSE_SLOT_INARTICLE: optional, numeric slot ID for an in-article ad
"""

@app.context_processor
def inject_adsense_ids():
    return {
        'ADSENSE_CLIENT': os.getenv('ADSENSE_CLIENT', ''),
        'ADSENSE_SLOT_TOP': os.getenv('ADSENSE_SLOT_TOP', ''),
        'ADSENSE_SLOT_INARTICLE': os.getenv('ADSENSE_SLOT_INARTICLE', ''),
    }

"""MongoDB (Atlas) setup"""
MONGODB_URI = os.getenv('MONGODB_URI')
MONGO_DB = os.getenv('MONGO_DB', 'fashiondb')
MONGO_COLLECTION = os.getenv('MONGO_COLLECTION', 'products')
MONGO_POSTS_COLLECTION = os.getenv('MONGO_POSTS_COLLECTION', 'posts')

_mongo_client = None
def get_products_coll():
    global _mongo_client
    if not MONGODB_URI:
        return None
    try:
        if _mongo_client is None:
            print("Attempting to connect to MongoDB...")
            # Set a timeout to avoid long hangs
            _mongo_client = MongoClient(MONGODB_URI, serverSelectionTimeoutMS=5000)
            # Verify connection/auth
            _mongo_client.admin.command('ping')
            print("MongoDB connected successfully!")
        db = _mongo_client[MONGO_DB]
        return db[MONGO_COLLECTION]
    except Exception:
        # Log full traceback to console for debugging
        print('Mongo connection error (products):')
        traceback.print_exc()
        return None

def get_posts_coll():
    """Get the MongoDB collection for blog posts, sharing the same client."""
    global _mongo_client
    if not MONGODB_URI:
        return None
    try:
        if _mongo_client is None:
            print("Attempting to connect to MongoDB...")
            _mongo_client = MongoClient(MONGODB_URI, serverSelectionTimeoutMS=5000)
            _mongo_client.admin.command('ping')
            print("MongoDB connected successfully!")
        db = _mongo_client[MONGO_DB]
        return db[MONGO_POSTS_COLLECTION]
    except Exception:
        print('Mongo connection error (posts):')
        traceback.print_exc()
        return None

def product_to_json(doc):
    if not doc:
        return None
    return {
        '_id': str(doc.get('_id')),
        'name': doc.get('name'),
        'category': doc.get('category'),
        'price': doc.get('price'),
        'rating': doc.get('rating'),
        'image': doc.get('image'),
        'affiliate_link': doc.get('affiliate_link'),
    }

def post_to_json(doc):
    if not doc:
        return None
    return {
        'id': str(doc.get('_id')),
        'title': doc.get('title'),
        'category': doc.get('category') or 'general',
        'date': doc.get('date') or '',
        'image': doc.get('image') or '',
        'excerpt': doc.get('excerpt') or '',
        'content': doc.get('content') or '',
    }

BLOG_POSTS = []  # Deprecated; blog now reads from Mongo if configured

@app.route('/')
def home():
    products = []
    coll = get_products_coll()
    if coll is not None:
        products = [product_to_json(p) for p in coll.find().sort('_id', -1)]
    # Pull a few recent posts if DB configured
    recent_posts = []
    posts_coll = get_posts_coll()
    if posts_coll is not None:
        recent_posts = [post_to_json(p) for p in posts_coll.find().sort('_id', -1).limit(3)]
    return render_template('index.html', 
                         featured_products=products, 
                         blog_posts=recent_posts)

@app.route('/blog')
def blog():
    posts = []
    coll = get_posts_coll()
    if coll is not None:
        posts = [post_to_json(p) for p in coll.find().sort('_id', -1)]
    return render_template('blog.html', blog_posts=posts)

@app.route('/blog/<int:post_id>')
def blog_post(post_id):
    # Support legacy integer IDs only if using in-memory posts
    coll = get_posts_coll()
    post = None
    if coll is not None:
        # In DB we use ObjectId strings; route expects int. Provide redirect.
        return redirect(url_for('blog'))
    else:
        post = next((p for p in BLOG_POSTS if p['id'] == post_id), None)
        if not post:
            return redirect(url_for('blog'))
        comparison_products = []
        return render_template('blog_post.html', post=post, products=comparison_products)

@app.route('/blog/view/<string:post_id>')
def blog_post_view(post_id):
    """View a blog post by its Mongo ObjectId string."""
    coll = get_posts_coll()
    if coll is None:
        return redirect(url_for('blog'))
    try:
        doc = coll.find_one({'_id': ObjectId(post_id)})
        if not doc:
            return redirect(url_for('blog'))
        post = post_to_json(doc)
        comparison_products = []
        return render_template('blog_post.html', post=post, products=comparison_products)
    except Exception:
        traceback.print_exc()
        return redirect(url_for('blog'))

"""Blog Post APIs"""
@app.route('/api/posts', methods=['GET'])
def api_get_posts():
    coll = get_posts_coll()
    if coll is None:
        return jsonify({'posts': []})
    posts = [post_to_json(p) for p in coll.find().sort('_id', -1)]
    return jsonify({'posts': posts})

@app.route('/api/posts', methods=['POST'])
@basic_auth.required
def api_add_post():
    try:
        data = request.get_json() or {}
        required = ['title', 'category', 'image', 'excerpt', 'content']
        if not all(k in data and data[k] for k in required):
            return jsonify({'success': False, 'message': 'All fields are required'}), 400
        coll = get_posts_coll()
        if coll is None:
            return jsonify({'success': False, 'message': 'Database not configured'}), 500
        doc = {
            'title': data['title'],
            'category': data['category'],
            'image': data['image'],
            'excerpt': data['excerpt'],
            'content': data['content'],
            'date': data.get('date') or '',
        }
        res = coll.insert_one(doc)
        saved = coll.find_one({'_id': res.inserted_id})
        return jsonify({'success': True, 'message': 'Post added successfully', 'post': post_to_json(saved)})
    except Exception as e:
        traceback.print_exc()
        return jsonify({'success': False, 'message': f'Failed to add post: {str(e)}'}), 500

@app.route('/api/posts/<string:post_id>', methods=['PUT'])
@basic_auth.required
def api_update_post(post_id):
    try:
        data = request.get_json() or {}
        required = ['title', 'category', 'image', 'excerpt', 'content']
        if not all(k in data and data[k] for k in required):
            return jsonify({'success': False, 'message': 'All fields are required'}), 400
        coll = get_posts_coll()
        if coll is None:
            return jsonify({'success': False, 'message': 'Database not configured'}), 500
        update_doc = {'$set': {
            'title': data['title'],
            'category': data['category'],
            'image': data['image'],
            'excerpt': data['excerpt'],
            'content': data['content'],
            'date': data.get('date') or '',
        }}
        result = coll.update_one({'_id': ObjectId(post_id)}, update_doc)
        if result.matched_count == 0:
            return jsonify({'success': False, 'message': 'Post not found'}), 404
        updated = coll.find_one({'_id': ObjectId(post_id)})
        return jsonify({'success': True, 'message': 'Post updated successfully', 'post': post_to_json(updated)})
    except Exception as e:
        traceback.print_exc()
        return jsonify({'success': False, 'message': f'Failed to update post: {str(e)}'}), 500

@app.route('/api/posts/<string:post_id>', methods=['DELETE'])
@basic_auth.required
def api_delete_post(post_id):
    try:
        coll = get_posts_coll()
        if coll is None:
            return jsonify({'success': False, 'message': 'Database not configured'}), 500
        res = coll.delete_one({'_id': ObjectId(post_id)})
        if res.deleted_count == 0:
            return jsonify({'success': False, 'message': 'Post not found'}), 404
        return jsonify({'success': True, 'message': 'Post deleted'})
    except Exception:
        traceback.print_exc()
        return jsonify({'success': False, 'message': 'Failed to delete post'}), 500

@app.route('/categories/<category>')
def category(category):
    category_products = []
    coll = get_products_coll()
    if coll is not None:
        category_products = [product_to_json(p) for p in coll.find({'category': category})]
    return render_template('category.html', 
                         category=category.title(), 
                         products=category_products)

@app.route('/about')
def about():
    return render_template('about.html')

@app.route('/contact')
def contact():
    return render_template('contact.html')

@app.route('/disclaimer')
def disclaimer():
    return render_template('disclaimer.html')

@app.route('/privacy')
def privacy():
    return render_template('privacy.html')

@app.route('/admin')
@basic_auth.required
def admin():
    return render_template('admin.html')

@app.route('/admin/blog')
@basic_auth.required
def admin_blog():
    return render_template('admin_blog.html')

@app.route('/robots.txt')
def robots_txt():
    """Permit Google AdSense and general crawling."""
    content = (
        "User-agent: *\n"
        "Allow: /\n"
        "Sitemap: " + request.url_root.rstrip('/') + "/sitemap.xml\n"
        "User-agent: Mediapartners-Google\n"
        "Allow: /\n"
    )
    return Response(content, mimetype='text/plain')

@app.route('/ads.txt')
def ads_txt():
    """Serve ads.txt from env if provided; otherwise minimal placeholder.

    Set ADS_TXT_CONTENT in environment to your exact AdSense-provided lines,
    e.g., "google.com, pub-1234567890123456, DIRECT, f08c47fec0942fa0".
    """
    content = os.getenv('ADS_TXT_CONTENT', '').strip()
    if not content:
        # Placeholder advises configuring ADS_TXT_CONTENT
        content = (
            "# Configure ADS_TXT_CONTENT env var with your ads.txt entries\n"
            "# Example (replace with your own):\n"
            "# google.com, pub-1234567890123456, DIRECT, f08c47fec0942fa0\n"
        )
    return Response(content + ("\n" if not content.endswith("\n") else ""), mimetype='text/plain')

@app.route('/api/products', methods=['GET'])
def get_products():
    coll = get_products_coll()
    if coll is None:
        return jsonify({'products': []})
    products = [product_to_json(p) for p in coll.find().sort('_id', -1)]
    return jsonify({'products': products})

@app.route('/api/products', methods=['POST'])
@basic_auth.required
def add_product():
    try:
        data = request.get_json() or {}
        required = ['name', 'category', 'price', 'rating', 'image', 'affiliate_link']
        if not all(k in data and data[k] for k in required):
            return jsonify({'success': False, 'message': 'All fields are required'}), 400

        coll = get_products_coll()
        if coll is None:
            return jsonify({'success': False, 'message': 'Database not configured'}), 500
        doc = {
            'name': data['name'],
            'category': data['category'],
            'price': data['price'],
            'rating': float(data['rating']),
            'image': data['image'],
            'affiliate_link': data['affiliate_link']
        }
        result = coll.insert_one(doc)
        saved = coll.find_one({'_id': result.inserted_id})
        return jsonify({'success': True, 'message': 'Product added successfully', 'product': product_to_json(saved)})
    except Exception as e:
        traceback.print_exc()
        return jsonify({'success': False, 'message': f'Failed to add product: {str(e)}'}), 500

@app.route('/api/products/<string:product_id>', methods=['PUT'])
@basic_auth.required
def update_product(product_id):
    try:
        data = request.get_json() or {}
        required = ['name', 'category', 'price', 'rating', 'image', 'affiliate_link']
        if not all(k in data and data[k] for k in required):
            return jsonify({'success': False, 'message': 'All product fields are required'}), 400

        coll = get_products_coll()
        if coll is None:
            return jsonify({'success': False, 'message': 'Database not configured'}), 500

        update_doc = {'$set': {
            'name': data['name'],
            'category': data['category'],
            'price': data['price'],
            'rating': data['rating'],
            'image': data['image'],
            'affiliate_link': data['affiliate_link'],
        }}
        result = coll.update_one({'_id': ObjectId(product_id)}, update_doc)
        if result.matched_count == 0:
            return jsonify({'success': False, 'message': 'Product not found'}), 404

        updated = coll.find_one({'_id': ObjectId(product_id)})
        return jsonify({'success': True, 'message': 'Product updated successfully', 'post': product_to_json(updated)})
    except Exception as e:
        traceback.print_exc()
        return jsonify({'success': False, 'message': f'Failed to update product: {str(e)}'}), 500

@app.route('/api/products/<string:product_id>', methods=['DELETE'])
@basic_auth.required
def delete_product(product_id):
    try:
        coll = get_products_coll()
        if coll is None:
            return jsonify({'success': False, 'message': 'Database not configured'}), 500
        oid = ObjectId(product_id)
        res = coll.delete_one({'_id': oid})
        if res.deleted_count == 0:
            return jsonify({'success': False, 'message': 'Product not found'}), 404
        return jsonify({'success': True, 'message': 'Product deleted'})
    except Exception:
        traceback.print_exc()
        return jsonify({'success': False, 'message': 'Failed to delete product'}), 500

@app.route('/api/subscribe', methods=['POST'])
def subscribe():
    try:
        data = request.get_json()
        email = data.get('email')
        
        if not email:
            return jsonify({'success': False, 'message': 'Email is required'}), 400
        
        # Send welcome email
        # msg = Message(
        #     'Welcome to Fashion Deals Weekly!',
        #     sender=app.config['MAIL_USERNAME'],
        #     recipients=[email]
        # )
        # msg.body = '''
        # Thank you for subscribing to Fashion Deals Weekly!
        
        # You'll receive the best fashion deals and style tips directly in your inbox.
        
        # Happy shopping!
        # The Fashion Team
        # '''
        
        # # In production, you'd save the email to a database here
        # # For now, we'll just send the welcome email
        # mail.send(msg)
        
        return jsonify({'success': True, 'message': 'Successfully subscribed!'})
    
    except Exception as e:
        return jsonify({'success': False, 'message': 'Subscription failed. Please try again.'}), 500

@app.route('/api/contact', methods=['POST'])
def contact_form():
    try:
        data = request.get_json()
        name = data.get('name')
        email = data.get('email')
        message = data.get('message')
        
        if not all([name, email, message]):
            return jsonify({'success': False, 'message': 'All fields are required'}), 400
        
        # Send contact email
        # msg = Message(
        #     f'Contact Form: {name}',
        #     sender=app.config['MAIL_USERNAME'],
        #     recipients=[app.config['MAIL_USERNAME']]
        # )
        # msg.body = f'''
        # New contact form submission:
        
        # Name: {name}
        # Email: {email}
        # Message: {message}
        # '''
        
        # mail.send(msg)
        
        return jsonify({'success': True, 'message': 'Message sent successfully!'})
    
    except Exception as e:
        return jsonify({'success': False, 'message': 'Failed to send message. Please try again.'}), 500

if __name__ == '__main__':
    app.run(debug=True)
