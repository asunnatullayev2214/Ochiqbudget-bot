from flask import Flask, render_template, jsonify, request
import os
import sqlite3
from datetime import datetime

app = Flask(__name__)

# Database setup
def init_db():
    conn = sqlite3.connect('database.db')
    c = conn.cursor()
    
    c.execute('''CREATE TABLE IF NOT EXISTS users
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  telegram_id INTEGER UNIQUE,
                  username TEXT,
                  full_name TEXT,
                  balance INTEGER DEFAULT 0,
                  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
    
    c.execute('''CREATE TABLE IF NOT EXISTS votes
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  user_id INTEGER,
                  phone TEXT,
                  status TEXT DEFAULT 'pending',
                  sms_code TEXT,
                  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                  verified_at TIMESTAMP,
                  FOREIGN KEY (user_id) REFERENCES users (id))''')
    
    conn.commit()
    conn.close()

init_db()

@app.route('/')
def home():
    return '''
    <!DOCTYPE html>
<html>
<head>
    <title>Ovoz Bot - 30,000 so'm bonus</title>
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <style>
        body {
            font-family: Arial, sans-serif;
            text-align: center;
            padding: 40px;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            min-height: 100vh;
            display: flex;
            justify-content: center;
            align-items: center;
        }
        .container {
            background: white;
            padding: 40px;
            border-radius: 20px;
            box-shadow: 0 20px 60px rgba(0,0,0,0.3);
            max-width: 500px;
            width: 100%;
        }
        h1 {
            color: #333;
            margin-bottom: 20px;
        }
        .bonus {
            background: linear-gradient(45deg, #FFD700, #FFA500);
            color: white;
            padding: 25px;
            border-radius: 15px;
            font-size: 32px;
            font-weight: bold;
            margin: 25px 0;
        }
        .telegram-btn {
            background: linear-gradient(45deg, #0088cc, #34b7f1);
            color: white;
            padding: 18px 40px;
            border-radius: 50px;
            text-decoration: none;
            font-size: 20px;
            font-weight: bold;
            display: inline-block;
            margin: 20px 0;
        }
        .steps {
            text-align: left;
            margin: 30px 0;
            padding: 20px;
            background: #f8f9fa;
            border-radius: 10px;
        }
        .step {
            margin: 15px 0;
            padding-left: 30px;
            position: relative;
        }
        .step:before {
            content: "✓";
            color: #28a745;
            font-weight: bold;
            position: absolute;
            left: 0;
        }
    </style>
</head>
<body>
    <div class="container">
        <h1>🎉 Ovoz Berish Boti</h1>
        <div class="bonus">+30,000 so'm bonus</div>
        
        <div class="steps">
            <div class="step">Telegramda @Ochiqbudgets_bot oching</div>
            <div class="step">Botda /start bosing</div>
            <div class="step">Web ilovani oching va telefon raqamingizni kiriting</div>
            <div class="step">SMS kodni oling va tasdiqlang</div>
            <div class="step">30,000 so'm bonusni oling</div>
        </div>
        
        <a href="https://t.me/Ochiqbudgets_bot" class="telegram-btn" target="_blank">
            📲 @Ochiqbudgets_bot
        </a>
        
        <p style="color: #666; margin-top: 20px;">
            Ko'proq ovoz bersangiz, ko'proq pul topasiz!
        </p>
    </div>
</body>
</html>
    '''

@app.route('/api/stats')
def stats():
    conn = sqlite3.connect('database.db')
    c = conn.cursor()
    
    c.execute("SELECT COUNT(*) FROM users")
    total_users = c.fetchone()[0] or 0
    
    c.execute("SELECT COUNT(*) FROM votes WHERE status='verified'")
    verified_votes = c.fetchone()[0] or 0
    
    c.execute("SELECT SUM(balance) FROM users")
    total_bonus = c.fetchone()[0] or 0
    
    conn.close()
    
    return jsonify({
        'total_users': total_users,
        'verified_votes': verified_votes,
        'total_bonus': total_bonus,
        'active_users': total_users
    })

@app.route('/health')
def health():
    return jsonify({'status': 'ok', 'time': datetime.now().isoformat()})

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
