#!/usr/bin/env python3
"""
Generate standalone HTML viewer for discovery items
Fetches all items from database and creates self-contained HTML file

Usage:
    python tools/generate_items_viewer.py
"""

import sys
import os
import json

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utilities.postgres_utils import get_db_connection

def fetch_all_items():
    """Fetch all discovery items from database"""
    conn = None
    cur = None
    
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        
        cur.execute("""
            SELECT id, item_name, item_type, rarity, description, 
                   weight_kg, stackable, preferred_mars_features,
                   min_distance_km, max_distance_km, base_scientific_value,
                   base_trade_value_eth, exploration_enhancement_value,
                   image_url, attributes
            FROM pilgrim.discovery_items
            ORDER BY rarity DESC, item_name
        """)
        
        items = []
        for row in cur.fetchall():
            items.append({
                'id': row[0],
                'item_name': row[1],
                'item_type': row[2],
                'rarity': row[3],
                'description': row[4],
                'weight_kg': float(row[5]) if row[5] else 0,
                'stackable': row[6],
                'preferred_mars_features': row[7],
                'min_distance_km': float(row[8]) if row[8] else 0,
                'max_distance_km': float(row[9]) if row[9] else None,
                'base_scientific_value': row[10],
                'base_trade_value_eth': float(row[11]) if row[11] else 0,
                'exploration_enhancement_value': float(row[12]) if row[12] else 0,
                'image_url': row[13],
                'attributes': row[14] if row[14] else {}
            })
        
        return items
        
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()

def generate_html(items):
    """Generate standalone HTML with embedded data"""
    
    items_json = json.dumps(items, indent=2)
    
    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Discovery Items Catalog</title>
    <style>
        * {{
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }}
        
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Oxygen, Ubuntu, Cantarell, sans-serif;
            background: linear-gradient(135deg, #1a1a2e 0%, #16213e 100%);
            color: #fff;
            padding: 40px 20px;
            min-height: 100vh;
        }}
        
        .container {{
            max-width: 1400px;
            margin: 0 auto;
        }}
        
        h1 {{
            text-align: center;
            margin-bottom: 40px;
            font-size: 2.5rem;
            background: linear-gradient(45deg, #667eea, #764ba2);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            background-clip: text;
        }}
        
        .stats {{
            display: flex;
            gap: 20px;
            justify-content: center;
            margin-bottom: 40px;
            flex-wrap: wrap;
        }}
        
        .stat-box {{
            background: rgba(255,255,255,0.1);
            padding: 15px 30px;
            border-radius: 10px;
            backdrop-filter: blur(10px);
        }}
        
        .stat-box .label {{
            font-size: 0.9rem;
            opacity: 0.7;
            margin-bottom: 5px;
        }}
        
        .stat-box .value {{
            font-size: 1.5rem;
            font-weight: bold;
        }}
        
        .filters {{
            display: flex;
            gap: 15px;
            margin-bottom: 30px;
            flex-wrap: wrap;
            justify-content: center;
        }}
        
        .filter-btn {{
            padding: 10px 20px;
            border: 2px solid rgba(255,255,255,0.2);
            background: rgba(255,255,255,0.1);
            color: white;
            border-radius: 20px;
            cursor: pointer;
            transition: all 0.3s;
            font-size: 0.9rem;
        }}
        
        .filter-btn:hover {{
            background: rgba(255,255,255,0.2);
            border-color: rgba(255,255,255,0.4);
        }}
        
        .filter-btn.active {{
            background: linear-gradient(45deg, #667eea, #764ba2);
            border-color: transparent;
        }}
        
        .items-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fill, minmax(350px, 1fr));
            gap: 25px;
            margin-bottom: 40px;
        }}
        
        .item-card {{
            background: rgba(255,255,255,0.05);
            border: 1px solid rgba(255,255,255,0.1);
            border-radius: 15px;
            overflow: hidden;
            transition: transform 0.3s, box-shadow 0.3s;
            backdrop-filter: blur(10px);
        }}
        
        .item-card:hover {{
            transform: translateY(-5px);
            box-shadow: 0 10px 30px rgba(0,0,0,0.3);
        }}
        
        .item-image {{
            width: 100%;
            height: 250px;
            object-fit: cover;
            background: linear-gradient(135deg, #1a1a2e 0%, #16213e 100%);
        }}
        
        .item-content {{
            padding: 20px;
        }}
        
        .item-header {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 10px;
        }}
        
        .item-name {{
            font-size: 1.3rem;
            font-weight: bold;
            color: #667eea;
        }}
        
        .item-rarity {{
            padding: 5px 12px;
            border-radius: 15px;
            font-size: 0.8rem;
            font-weight: bold;
            text-transform: uppercase;
        }}
        
        .rarity-common {{ background: #6c757d; }}
        .rarity-uncommon {{ background: #28a745; }}
        .rarity-rare {{ background: #007bff; }}
        .rarity-legendary {{ background: #ffc107; color: #000; }}
        
        .item-type {{
            display: inline-block;
            padding: 4px 10px;
            background: rgba(255,255,255,0.1);
            border-radius: 10px;
            font-size: 0.85rem;
            margin-bottom: 10px;
        }}
        
        .item-description {{
            font-size: 0.95rem;
            line-height: 1.5;
            margin-bottom: 15px;
            opacity: 0.9;
        }}
        
        .item-stats {{
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 10px;
            margin: 15px 0;
            padding: 15px;
            background: rgba(0,0,0,0.2);
            border-radius: 10px;
        }}
        
        .item-stat {{
            font-size: 0.85rem;
        }}
        
        .item-stat .label {{
            opacity: 0.7;
            margin-bottom: 3px;
        }}
        
        .item-stat .value {{
            font-weight: bold;
            color: #667eea;
        }}
        
        .item-features {{
            display: flex;
            flex-wrap: wrap;
            gap: 8px;
            margin-top: 15px;
        }}
        
        .feature-tag {{
            padding: 5px 10px;
            background: rgba(102, 126, 234, 0.2);
            border: 1px solid rgba(102, 126, 234, 0.4);
            border-radius: 5px;
            font-size: 0.8rem;
        }}
        
        .no-image {{
            display: flex;
            align-items: center;
            justify-content: center;
            height: 250px;
            background: rgba(255,255,255,0.05);
            font-size: 3rem;
            opacity: 0.3;
        }}
        
        .loading {{
            text-align: center;
            padding: 60px;
            font-size: 1.2rem;
            opacity: 0.7;
        }}
    </style>
</head>
<body>
    <div class="container">
        <h1>🔴 Discovery Items Catalog</h1>
        
        <div class="stats">
            <div class="stat-box">
                <div class="label">Total Items</div>
                <div class="value" id="totalItems">0</div>
            </div>
            <div class="stat-box">
                <div class="label">With Images</div>
                <div class="value" id="withImages">0</div>
            </div>
            <div class="stat-box">
                <div class="label">Without Images</div>
                <div class="value" id="withoutImages">0</div>
            </div>
        </div>
        
        <div class="filters">
            <button class="filter-btn active" data-filter="all">All</button>
            <button class="filter-btn" data-filter="common">Common</button>
            <button class="filter-btn" data-filter="uncommon">Uncommon</button>
            <button class="filter-btn" data-filter="rare">Rare</button>
            <button class="filter-btn" data-filter="legendary">Legendary</button>
            <button class="filter-btn" data-filter="mineral">Mineral</button>
            <button class="filter-btn" data-filter="artifact">Artifact</button>
            <button class="filter-btn" data-filter="equipment">Equipment</button>
            <button class="filter-btn" data-filter="biological">Biological</button>
            <button class="filter-btn" data-filter="data">Data</button>
        </div>
        
        <div id="itemsContainer" class="items-grid">
            <div class="loading">Loading items...</div>
        </div>
    </div>
    
    <script>
        // Embedded data
        const allItems = {items_json};
        let currentFilter = 'all';
        
        function updateStats() {{
            const withImages = allItems.filter(item => item.image_url).length;
            
            document.getElementById('totalItems').textContent = allItems.length;
            document.getElementById('withImages').textContent = withImages;
            document.getElementById('withoutImages').textContent = allItems.length - withImages;
        }}
        
        function renderItems() {{
            const container = document.getElementById('itemsContainer');
            
            const filtered = allItems.filter(item => {{
                if (currentFilter === 'all') return true;
                return item.rarity === currentFilter || item.item_type === currentFilter;
            }});
            
            if (filtered.length === 0) {{
                container.innerHTML = '<div class="loading">No items found</div>';
                return;
            }}
            
            container.innerHTML = filtered.map(item => `
                <div class="item-card">
                    ${{item.image_url 
                        ? `<img src="${{item.image_url}}" alt="${{item.item_name}}" class="item-image">`
                        : '<div class="no-image">📦</div>'
                    }}
                    <div class="item-content">
                        <div class="item-header">
                            <div class="item-name">${{item.item_name}}</div>
                            <div class="item-rarity rarity-${{item.rarity}}">${{item.rarity}}</div>
                        </div>
                        <div class="item-type">${{item.item_type}}</div>
                        <div class="item-description">${{item.description}}</div>
                        
                        <div class="item-stats">
                            <div class="item-stat">
                                <div class="label">Weight</div>
                                <div class="value">${{item.weight_kg}} kg</div>
                            </div>
                            <div class="item-stat">
                                <div class="label">Stackable</div>
                                <div class="value">${{item.stackable ? 'Yes' : 'No'}}</div>
                            </div>
                            <div class="item-stat">
                                <div class="label">Scientific Value</div>
                                <div class="value">${{item.base_scientific_value}}</div>
                            </div>
                            <div class="item-stat">
                                <div class="label">Trade Value</div>
                                <div class="value">${{(item.base_trade_value_eth * 100000).toFixed(0)}} S</div>
                            </div>
                            <div class="item-stat">
                                <div class="label">Enhancement</div>
                                <div class="value">${{item.exploration_enhancement_value}}x</div>
                            </div>
                            <div class="item-stat">
                                <div class="label">Distance Range</div>
                                <div class="value">${{item.min_distance_km}}-${{item.max_distance_km || '∞'}} km</div>
                            </div>
                        </div>
                        
                        <div class="item-features">
                            ${{item.preferred_mars_features.map(f => 
                                `<span class="feature-tag">${{f}}</span>`
                            ).join('')}}
                        </div>
                    </div>
                </div>
            `).join('');
        }}
        
        // Filter buttons
        document.querySelectorAll('.filter-btn').forEach(btn => {{
            btn.addEventListener('click', () => {{
                document.querySelectorAll('.filter-btn').forEach(b => b.classList.remove('active'));
                btn.classList.add('active');
                currentFilter = btn.dataset.filter;
                renderItems();
            }});
        }});
        
        // Initialize
        updateStats();
        renderItems();
    </script>
</body>
</html>"""
    
    return html

def main():
    print("Fetching discovery items from database...")
    items = fetch_all_items()
    print(f"Found {len(items)} items")
    
    print("Generating HTML...")
    html = generate_html(items)
    
    output_file = os.path.join(os.path.dirname(__file__), 'discovery_items_viewer.html')
    with open(output_file, 'w', encoding='utf-8') as f:
        f.write(html)
    
    print(f"✅ Generated: {output_file}")
    print(f"Open in browser to view")

if __name__ == "__main__":
    main()