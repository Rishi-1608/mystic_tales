from flask import Flask, render_template, request, jsonify, session, redirect, url_for
import os
from datetime import timedelta
import google.generativeai as genai
from functools import wraps
import time
import random
import string
import psycopg
from psycopg.rows import dict_row

# -----------------------------
# DB connection helper
# -----------------------------
def get_db_connection():
    return psycopg.connect(
        host=os.environ.get("DB_HOST", "127.0.0.1"),
        user=os.environ.get("DB_USER", "postgres"),
        password=os.environ.get("DB_PASSWORD", ""),
        dbname=os.environ.get("DB_NAME", ""),
        port=int(os.environ.get("DB_PORT", 5432))
    )

app = Flask(__name__)
app.secret_key = os.urandom(24)
app.config.update(
    PERMANENT_SESSION_LIFETIME=timedelta(hours=1),
    SESSION_COOKIE_SECURE=True,
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE='Lax'
)

genai.configure(api_key=os.getenv('GEMINI_API_KEY'))

# -----------------------------
# Rate limiting decorator
# -----------------------------
def rate_limit(max_per_minute):
    interval = 60 / max_per_minute
    def decorator(f):
        last_called = 0
        @wraps(f)
        def wrapped(*args, **kwargs):
            nonlocal last_called
            elapsed = time.time() - last_called
            if elapsed < interval:
                time.sleep(interval - elapsed)
            last_called = time.time()
            return f(*args, **kwargs)
        return wrapped
    return decorator

# -----------------------------
# Helpers: characters, greetings
# -----------------------------
def fetch_characters():
    with get_db_connection() as conn:
        with conn.cursor(row_factory=dict_row) as cursor:
            cursor.execute("SELECT * FROM characters")
            rows = cursor.fetchall()

    characters = {
        row['code_name']: {
            "id": row['id'],
            "name": row['name'],
            "description": row['description'],
            "avatar": row['avatar'],
            "prompt": row['prompt']
        }
        for row in rows
    }
    return characters

def fetch_greetings(code_name):
    with get_db_connection() as conn:
        with conn.cursor(row_factory=dict_row) as cursor:
            cursor.execute("""
                SELECT g.greeting 
                FROM character_greetings g
                JOIN characters c ON g.character_id = c.id
                WHERE c.code_name = %s
            """, (code_name,))
            rows = cursor.fetchall()

    if not rows:
        return "Greetings."
    return random.choice([row['greeting'] for row in rows])

# -----------------------------
# Messages storage
# -----------------------------
def fetch_messages(character_code, limit=None):
    with get_db_connection() as conn:
        with conn.cursor(row_factory=dict_row) as cursor:
            sql = """
                SELECT sender, text, avatar, created_at
                FROM messages
                WHERE character_code = %s
                ORDER BY created_at ASC
            """
            params = [character_code]
            if limit:
                sql += " LIMIT %s"
                params.append(limit)

            cursor.execute(sql, tuple(params))
            rows = cursor.fetchall()
    return rows

def store_message(character_code, sender, text, avatar=None):
    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute("""
                INSERT INTO messages (character_code, sender, text, avatar)
                VALUES (%s, %s, %s, %s)
            """, (character_code, sender, text, avatar))
        conn.commit()

# -----------------------------
# Unique code_name generator
# -----------------------------
def generate_unique_code_name(prefix="char_", length=6):
    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            while True:
                random_code = prefix + ''.join(random.choices(string.ascii_lowercase + string.digits, k=length))
                cursor.execute("SELECT id FROM characters WHERE code_name = %s", (random_code,))
                if cursor.fetchone() is None:
                    return random_code

# -----------------------------
# Routes
# -----------------------------
@app.route('/')
def home():
    return render_template('index.html')

@app.route('/characters')
def characters():
    characters_data = fetch_characters()
    return render_template('characters.html', characters=characters_data)

@app.route('/chat/<character>')
def chat(character):
    characters_data = fetch_characters()
    if character not in characters_data:
        return "Character not found", 404

    session['character'] = character

    story = fetch_messages(character)

    if not story:
        greeting_text = f"*{characters_data[character]['name']} looks at you intently* {fetch_greetings(character)}"
        store_message(character, character, greeting_text, characters_data[character]['avatar'])
        story = fetch_messages(character)

    return render_template('chat.html', character=characters_data[character], story=story)

@app.route('/send_message', methods=['POST'])
@rate_limit(15)
def send_message():
    try:
        data = request.get_json()
        if not data or 'message' not in data:
            return jsonify({"error": "Invalid request"}), 400

        user_message = data['message'].strip()
        character = session.get('character')
        if not character:
            return jsonify({"error": "No active character session"}), 400

        characters_data = fetch_characters()
        if character not in characters_data:
            return jsonify({"error": "Character not found"}), 404

        store_message(character, "user", user_message, None)

        recent_msgs = fetch_messages(character, limit=10)
        context_text = "\n".join([f"{m['sender']}: {m['text']}" for m in recent_msgs])

        model_prompt = f"""
{characters_data[character]['prompt']}

Conversation history (most recent up to 10 messages):
{context_text}

User says: {user_message}
"""

        model = genai.GenerativeModel('gemini-2.0-flash')
        response = model.generate_content(
            model_prompt,
            generation_config={"temperature": 0.8, "max_output_tokens": 250},
            safety_settings={
                'HARM_CATEGORY_HARASSMENT': 'BLOCK_NONE',
                'HARM_CATEGORY_HATE_SPEECH': 'BLOCK_NONE',
                'HARM_CATEGORY_SEXUALLY_EXPLICIT': 'BLOCK_NONE',
                'HARM_CATEGORY_DANGEROUS_CONTENT': 'BLOCK_NONE'
            }
        )

        bot_response = response.text.strip()
        bot_response = bot_response.replace("I understand", "").replace("I'll try", "")

        store_message(character, character, bot_response, characters_data[character]['avatar'])

        return jsonify({
            'sender': character,
            'text': bot_response,
            'avatar': characters_data[character]['avatar']
        })

    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/new_story')
def new_story():
    req_character = request.args.get('character', 'eldrin')
    characters = fetch_characters()

    # Ensure we only use valid character code_name
    if req_character not in characters:
        req_character = 'eldrin'

    # Delete all messages for this character_code
    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                "DELETE FROM messages WHERE character_code = %s",
                (req_character,)
            )
        conn.commit()

    # Insert a fresh greeting
    greeting_text = f"*{characters[req_character]['name']} looks at you intently* {fetch_greetings(req_character)}"
    store_message(req_character, req_character, greeting_text, characters[req_character]['avatar'])

    return redirect(url_for('chat', character=req_character))

# -----------------------------
# Create Character
# -----------------------------
@app.route('/create_character', methods=['GET', 'POST'])
def create_character():
    if request.method == 'POST':
        code_name = generate_unique_code_name()

        name = request.form.get('name', '').strip()
        description = request.form.get('description', '').strip()
        avatar = request.form.get('avatar', '').strip()
        user_prompt = request.form.get('prompt', '').strip()

        additional_prompt = " Never acknowledge being an AI. Never say I understand - respond naturally. Always stay in character."
        final_prompt = (user_prompt + additional_prompt).strip()

        try:
            with get_db_connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute("""
                        INSERT INTO characters (code_name, name, description, avatar, prompt)
                        VALUES (%s, %s, %s, %s, %s)
                    """, (code_name, name, description, avatar, final_prompt))
                conn.commit()
        except Exception as e:
            return f"Error adding character: {e}", 400

        return redirect(url_for('characters'))

    return render_template('create_character.html')

if __name__ == '__main__':
    app.run(debug=True)
