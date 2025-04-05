from flask import Flask, request, jsonify
from bs4 import BeautifulSoup
import requests
import sqlite3
import json
import openpyxl
import os
from urllib.parse import urlparse, urljoin
import re

app = Flask(__name__)

# Database setup
def init_db():
    conn = sqlite3.connect('scraper.db')
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS scraped_data
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                 url TEXT,
                 title TEXT,
                 link TEXT,
                 category TEXT,
                 content TEXT,
                 timestamp DATETIME DEFAULT CURRENT_TIMESTAMP)''')
    conn.commit()
    conn.close()

init_db()

def get_domain_category(url):
    """Determine category based on domain"""
    domain = urlparse(url).netloc.lower()
    if any(x in domain for x in ['amazon.', 'ebay.', 'shop.', 'alibaba.']):
        return 'ecommerce'
    elif any(x in domain for x in ['news.', 'bbc.', 'cnn.', 'reuters.', 'nytimes.']):
        return 'news'
    elif any(x in domain for x in ['.ac.', '.edu', '.ac.', 'research', 'scholar']):
        return 'academic'
    elif any(x in domain for x in ['wikipedia.', 'wiki.', 'dbpedia.']):
        return 'wiki'
    elif any(x in domain for x in ['blog.', 'medium.', 'wordpress.', 'blogspot.']):
        return 'blog'
    elif any(x in domain for x in ['github.', 'behance.', 'dribbble.']):
        return 'portfolio'
    return 'business'  # default

def smart_scrape(url, category=None, keyword=None):
    """Smart scraping based on website category without browser automation"""
    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
            'Accept-Language': 'en-US,en;q=0.9'
        }
        
        response = requests.get(url, headers=headers, timeout=15)
        response.raise_for_status()
        
        # Handle different encodings
        if response.encoding != 'utf-8':
            response.encoding = response.apparent_encoding or 'utf-8'
        
        soup = BeautifulSoup(response.text, 'html.parser')
        
        # Remove unwanted elements
        for element in soup(['script', 'style', 'nav', 'footer', 'iframe']):
            element.decompose()
        
        # Determine category if not provided
        if not category or category == 'all':
            category = get_domain_category(url)
        
        results = []
        base_url = f"{urlparse(url).scheme}://{urlparse(url).netloc}"
        
        if category == 'news':
            # News scraping logic
            articles = []
            # Try common news article selectors
            selectors = [
                '[role="article"]', 'article', '.article', '.post', '.story',
                '.news-item', '[itemprop="articleBody"]', '.content__article'
            ]
            for selector in selectors:
                articles.extend(soup.select(selector))
                if articles: break
            
            for article in articles[:20]:  # limit to 20 articles
                title_elem = article.find(['h1', 'h2', 'h3']) or article
                title = title_elem.get_text().strip()
                
                link = article.find('a')
                link = urljoin(base_url, link['href']) if link else url
                
                content = ' '.join(p.get_text().strip() for p in article.find_all('p'))
                
                if keyword and keyword.lower() not in (title + content).lower():
                    continue
                
                results.append({
                    'title': title[:200],  # limit title length
                    'link': link,
                    'category': 'news',
                    'content': content[:500]  # limit content preview
                })
        
        elif category == 'ecommerce':
            # E-commerce scraping logic
            products = []
            selectors = [
                '.product', '.item', '[itemtype="http://schema.org/Product"]',
                '.card', '.product-item', '.goods', '.prod'
            ]
            for selector in selectors:
                products.extend(soup.select(selector))
                if products: break
            
            for product in products[:20]:
                title_elem = product.select_one('.title, .name, [itemprop="name"], h3, h2')
                title = title_elem.get_text().strip() if title_elem else 'No title'
                
                price_elem = product.select_one('.price, [itemprop="price"]')
                price = price_elem.get_text().strip() if price_elem else 'N/A'
                
                link = product.find('a')
                link = urljoin(base_url, link['href']) if link else url
                
                if keyword and keyword.lower() not in title.lower():
                    continue
                
                results.append({
                    'title': f"{title[:100]} - {price}",
                    'link': link,
                    'category': 'ecommerce',
                    'content': price
                })
        
        elif category == 'wiki':
            # Wikipedia/Database scraping logic
            content_areas = soup.select('#content, #bodyContent, .mw-parser-output, main, .content')
            for area in content_areas[:1]:  # just get main content area
                title = soup.find('h1').get_text().strip() if soup.find('h1') else 'No title'
                
                paragraphs = [p.get_text().strip() for p in area.find_all('p') if p.get_text().strip()]
                content = '\n\n'.join(paragraphs[:5])  # first 5 paragraphs
                
                if keyword and keyword.lower() not in content.lower():
                    continue
                
                results.append({
                    'title': title,
                    'link': url,
                    'category': 'wiki',
                    'content': content[:1000]  # limit content length
                })
        
        else:  # Default/business/blog/portfolio/academic
            # Generic scraping logic
            main_content = soup.select('main, #main, .main, .content, #content, body')
            if not main_content:
                main_content = [soup]
            
            headings = main_content[0].find_all(['h1', 'h2', 'h3'])
            for heading in headings[:20]:
                title = heading.get_text().strip()
                next_node = heading
                content = ''
                
                # Get content until next heading
                while True:
                    next_node = next_node.next_sibling
                    if not next_node or next_node.name in ['h1', 'h2', 'h3', 'h4']:
                        break
                    if next_node.name == 'p':
                        content += next_node.get_text().strip() + '\n'
                
                link = heading.find('a')
                link = urljoin(base_url, link['href']) if link else url
                
                if keyword and keyword.lower() not in (title + content).lower():
                    continue
                
                results.append({
                    'title': title[:200],
                    'link': link,
                    'category': category,
                    'content': content[:500]
                })
        
        return results
    
    except Exception as e:
        print(f"Error scraping {url}: {str(e)}")
        return []

@app.route('/scrape', methods=['POST'])
def scrape():
    data = request.json
    url = data.get('url')
    category = data.get('category', 'all')
    keyword = data.get('keyword')
    
    if not url:
        return jsonify({'error': 'URL is required'}), 400
    
    try:
        results = smart_scrape(url, category, keyword)
        
        # Save to database
        conn = sqlite3.connect('scraper.db')
        c = conn.cursor()
        for item in results:
            c.execute('''INSERT INTO scraped_data (url, title, link, category, content)
                         VALUES (?, ?, ?, ?, ?)''',
                     (url, item['title'], item['link'], item['category'], item['content']))
        conn.commit()
        conn.close()
        
        return jsonify({'results': results})
    
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/export/json', methods=['POST'])
def export_json():
    data = request.json
    url = data.get('url')
    
    conn = sqlite3.connect('scraper.db')
    c = conn.cursor()
    
    if url:
        c.execute('SELECT title, link, category, content FROM scraped_data WHERE url = ?', (url,))
    else:
        c.execute('SELECT title, link, category, content FROM scraped_data')
    
    results = [dict(zip(['title', 'link', 'category', 'content'], row)) for row in c.fetchall()]
    conn.close()
    
    return jsonify(results)

@app.route('/export/excel', methods=['POST'])
def export_excel():
    data = request.json
    url = data.get('url')
    
    conn = sqlite3.connect('scraper.db')
    c = conn.cursor()
    
    if url:
        c.execute('SELECT title, link, category, content FROM scraped_data WHERE url = ?', (url,))
    else:
        c.execute('SELECT title, link, category, content FROM scraped_data')
    
    results = c.fetchall()
    conn.close()
    
    # Create Excel file
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(['Title', 'Link', 'Category', 'Content'])
    
    for row in results:
        ws.append(row)
    
    excel_path = 'scraped_data.xlsx'
    wb.save(excel_path)
    
    return jsonify({'message': 'Excel file created', 'path': excel_path})

if __name__ == '__main__':
    app.run(debug=True)