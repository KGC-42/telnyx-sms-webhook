"""
Updated Telnyx SMS Webhook Server with Enhanced Debugging
Save this as: main.py
"""

from fastapi import FastAPI, Request
import json
import sqlite3
from datetime import datetime, timedelta
import re
import uvicorn
import os

app = FastAPI(title="Telnyx SMS Webhook", version="1.0.1")

def init_db():
    """Initialize SQLite database"""
    conn = sqlite3.connect('sms_messages.db')
    conn.execute('''CREATE TABLE IF NOT EXISTS sms_messages 
                   (id INTEGER PRIMARY KEY AUTOINCREMENT,
                    phone TEXT NOT NULL,
                    message TEXT NOT NULL,
                    timestamp TEXT NOT NULL,
                    extracted_code TEXT,
                    platform TEXT,
                    used INTEGER DEFAULT 0)''')
    conn.commit()
    conn.close()

init_db()

@app.get("/")
async def root():
    """Health check endpoint"""
    return {"status": "Telnyx SMS Webhook Server Running", "version": "1.0.1"}

@app.post("/webhook/telnyx")
async def receive_sms(request: Request):
    """Receive SMS from Telnyx webhook"""
    try:
        data = await request.json()
        print(f"Full webhook data received: {json.dumps(data, indent=2)}")
        
        # Handle different Telnyx webhook formats
        phone = None
        message_text = None
        received_at = datetime.now().isoformat()
        
        # Try multiple data extraction methods
        if data.get('event_type') == 'message.received':
            # New Telnyx format
            payload = data.get('data', {}).get('payload', {})
            phone = payload.get('from', {}).get('phone_number', '')
            message_text = payload.get('text', '')
            received_at = payload.get('received_at', received_at)
            print(f"Method 1 - New format: phone={phone}, message={message_text}")
        
        if not phone or not message_text:
            # Fallback method 1
            message_data = data.get('data', {})
            phone = message_data.get('from', {}).get('phone_number', '') if isinstance(message_data.get('from'), dict) else message_data.get('from', '')
            message_text = message_data.get('text', '') or message_data.get('body', '')
            received_at = message_data.get('received_at', received_at)
            print(f"Method 2 - Fallback: phone={phone}, message={message_text}")
        
        if not phone or not message_text:
            # Fallback method 2 - direct from data
            phone = data.get('from', {}).get('phone_number', '') if isinstance(data.get('from'), dict) else data.get('from', '')
            message_text = data.get('text', '') or data.get('body', '') or data.get('message', '')
            print(f"Method 3 - Direct: phone={phone}, message={message_text}")
        
        if not phone or not message_text:
            # Fallback method 3 - search all nested data
            def find_phone_and_message(obj, phone=None, message=None):
                if isinstance(obj, dict):
                    for key, value in obj.items():
                        if key in ['phone_number', 'from'] and isinstance(value, str) and value.startswith('+'):
                            phone = value
                        elif key in ['text', 'body', 'message'] and isinstance(value, str) and value:
                            message = value
                        elif isinstance(value, (dict, list)):
                            phone, message = find_phone_and_message(value, phone, message)
                elif isinstance(obj, list):
                    for item in obj:
                        phone, message = find_phone_and_message(item, phone, message)
                return phone, message
            
            phone, message_text = find_phone_and_message(data)
            print(f"Method 4 - Deep search: phone={phone}, message={message_text}")
        
        print(f"Final parsed data: phone='{phone}', message='{message_text}'")
        
        if not phone or not message_text:
            error_msg = f"Missing data - phone: '{phone}', message: '{message_text}'"
            print(error_msg)
            return {"status": "error", "message": error_msg, "received_data": data}
        
        # Extract verification code (common patterns)
        code_patterns = [
            r'\b(\d{6})\b',           # 6 digits
            r'\b(\d{5})\b',           # 5 digits  
            r'\b(\d{4})\b',           # 4 digits
            r'code[:\s]*(\d{4,8})',   # "code: 123456"
            r'verification[:\s]*(\d{4,8})',  # "verification: 123456"
        ]
        
        extracted_code = None
        for pattern in code_patterns:
            match = re.search(pattern, message_text, re.IGNORECASE)
            if match:
                extracted_code = match.group(1)
                break
        
        # Detect platform from message content
        platform = "unknown"
        message_lower = message_text.lower()
        
        if any(keyword in message_lower for keyword in ['instagram', 'ig']):
            platform = "instagram"
        elif any(keyword in message_lower for keyword in ['tiktok', 'tik tok']):
            platform = "tiktok"
        elif any(keyword in message_lower for keyword in ['youtube', 'google']):
            platform = "youtube"
        elif any(keyword in message_lower for keyword in ['twitter', 'x.com']):
            platform = "twitter"
        
        # Store in database
        conn = sqlite3.connect('sms_messages.db')
        conn.execute('''INSERT INTO sms_messages 
                       (phone, message, timestamp, extracted_code, platform) 
                       VALUES (?, ?, ?, ?, ?)''',
                    (phone, message_text, received_at, extracted_code, platform))
        conn.commit()
        conn.close()
        
        print(f"SMS stored successfully: {phone} | Platform: {platform} | Code: {extracted_code}")
        
        return {"status": "received", "code_extracted": bool(extracted_code), "phone": phone, "platform": platform}
        
    except Exception as e:
        error_msg = f"Webhook error: {str(e)}"
        print(error_msg)
        return {"status": "error", "message": error_msg}

@app.get("/get_code/{phone}")
async def get_latest_code(phone: str):
    """Get latest verification code for phone number"""
    try:
        conn = sqlite3.connect('sms_messages.db')
        cursor = conn.execute('''SELECT extracted_code, platform, timestamp 
                                FROM sms_messages 
                                WHERE phone = ? AND extracted_code IS NOT NULL 
                                ORDER BY timestamp DESC LIMIT 1''', (phone,))
        result = cursor.fetchone()
        conn.close()
        
        if result:
            return {
                "code": result[0],
                "platform": result[1],
                "timestamp": result[2]
            }
        else:
            return {"code": None, "message": "No codes found"}
            
    except Exception as e:
        return {"error": str(e)}

@app.get("/get_code/{phone}/{platform}")
async def get_platform_code(phone: str, platform: str):
    """Get verification code for specific platform"""
    try:
        conn = sqlite3.connect('sms_messages.db')
        cursor = conn.execute('''SELECT extracted_code, timestamp 
                                FROM sms_messages 
                                WHERE phone = ? AND platform = ? 
                                AND extracted_code IS NOT NULL 
                                AND used = 0
                                ORDER BY timestamp DESC LIMIT 1''', (phone, platform))
        result = cursor.fetchone()
        
        if result:
            # Mark as used
            conn.execute('''UPDATE sms_messages 
                           SET used = 1 
                           WHERE phone = ? AND platform = ? AND extracted_code = ?''',
                        (phone, platform, result[0]))
            conn.commit()
        
        conn.close()
        
        if result:
            return {
                "code": result[0],
                "timestamp": result[1],
                "platform": platform
            }
        else:
            return {"code": None, "message": f"No unused codes for {platform}"}
            
    except Exception as e:
        return {"error": str(e)}

@app.get("/messages/{phone}")
async def get_messages(phone: str, limit: int = 10):
    """Get recent messages for phone number"""
    try:
        conn = sqlite3.connect('sms_messages.db')
        cursor = conn.execute('''SELECT message, timestamp, extracted_code, platform 
                                FROM sms_messages 
                                WHERE phone = ? 
                                ORDER BY timestamp DESC LIMIT ?''', (phone, limit))
        results = cursor.fetchall()
        conn.close()
        
        messages = []
        for row in results:
            messages.append({
                "message": row[0],
                "timestamp": row[1],
                "extracted_code": row[2],
                "platform": row[3]
            })
        
        return {"phone": phone, "messages": messages}
        
    except Exception as e:
        return {"error": str(e)}

@app.get("/debug/{phone}")
async def debug_messages(phone: str):
    """Debug endpoint to see all data for a phone number"""
    try:
        conn = sqlite3.connect('sms_messages.db')
        cursor = conn.execute('''SELECT * FROM sms_messages WHERE phone = ? ORDER BY timestamp DESC''', (phone,))
        results = cursor.fetchall()
        conn.close()
        
        return {"phone": phone, "total_messages": len(results), "raw_data": results}
        
    except Exception as e:
        return {"error": str(e)}

@app.get("/health")
async def health_check():
    """Health check with database status"""
    try:
        conn = sqlite3.connect('sms_messages.db')
        cursor = conn.execute("SELECT COUNT(*) FROM sms_messages WHERE timestamp > ?", 
                             ((datetime.now() - timedelta(hours=24)).isoformat(),))
        count_24h = cursor.fetchone()[0]
        conn.close()
        
        return {
            "status": "healthy",
            "database": "connected",
            "messages_24h": count_24h
        }
    except Exception as e:
        return {"status": "error", "error": str(e)}

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0"
