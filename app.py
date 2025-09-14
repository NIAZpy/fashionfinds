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
            # The ping command is a lightweight way to verify connection and auth.
            _mongo_client.admin.command('ping')
            print("MongoDB connected successfully!")
        db = _mongo_client[MONGO_DB]
        return db[MONGO_COLLECTION]
    except Exception:
        # Log full traceback to console for debugging
        print('Mongo connection error:')
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

BLOG_POSTS = []  # No demo posts; wire up later when backend for posts is ready

@app.route('/')
def home():
    products = []
    coll = get_products_coll()
    if coll is not None:
        products = [product_to_json(p) for p in coll.find().sort('_id', -1)]
    return render_template('index.html', 
                         featured_products=products, 
                         blog_posts=BLOG_POSTS[:3])

@app.route('/blog')
def blog():
    return render_template('blog.html', blog_posts=BLOG_POSTS)

@app.route('/blog/<int:post_id>')
def blog_post(post_id):
    post = next((p for p in BLOG_POSTS if p['id'] == post_id), None)
    if not post:
        return redirect(url_for('blog'))
    
    # No demo comparison products
    comparison_products = []
    
    return render_template('blog_post.html', post=post, products=comparison_products)

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
