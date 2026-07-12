"""Computer Anudeshak Exam Prep Platform — Diagnostic-First Analytics Engine"""
import sqlite3, json, os, time, random, re, subprocess, hashlib, shutil
from datetime import datetime, timedelta
from contextlib import contextmanager
from flask import Flask, render_template, request, jsonify, g, session, redirect, url_for
from werkzeug.security import generate_password_hash, check_password_hash
from flask_session import Session

app = Flask(__name__)
app.secret_key = os.urandom(24)
app.config["SESSION_TYPE"] = "filesystem"
app.config["SESSION_FILE_DIR"] = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "flask_session")
Session(app)

# ─── JWT Auth ────────────────────────────────────────────────
from auth import create_token, verify_token, require_auth, DEFAULT_USER, DEFAULT_PASS

@app.route('/login', methods=['GET', 'POST'])
def login_page():
    error = None
    if request.method == 'POST':
        if request.form.get('username') == DEFAULT_USER and request.form.get('password') == DEFAULT_PASS:
            token = create_token(DEFAULT_USER)
            resp = redirect(url_for('index'))
            resp.set_cookie('auth_token', token, httponly=True, samesite='Lax')
            session['auth_token'] = token
            return resp
        error = 'Invalid credentials'
    return render_template('login.html', error=error)

@app.route('/logout')
def logout():
    session.pop('auth_token', None)
    resp = redirect(url_for('login_page'))
    resp.delete_cookie('auth_token')
    return resp

@app.before_request
def check_auth():
    """Require authentication for all routes except login and static"""
    if request.endpoint in ('login_page', 'static', None):
        return
    token = request.cookies.get("auth_token") or session.get("auth_token")
    if not token or not verify_token(token):
        if request.endpoint and request.endpoint.startswith('api'):
            return jsonify({"error": "Unauthorized"}), 401
        return redirect(url_for('login_page'))
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, 'data', 'exam_prep.db')

# ─── Database Setup ───────────────────────────────────────────
def get_db():
    if 'db' not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA journal_mode=WAL")
        g.db.execute("PRAGMA foreign_keys=ON")
    return g.db

@app.teardown_appcontext
def close_db(e):
    db = g.pop('db', None)
    if db: db.close()

def init_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    db = sqlite3.connect(DB_PATH)
    db.executescript('''
        CREATE TABLE IF NOT EXISTS topics (
            id INTEGER PRIMARY KEY, name TEXT UNIQUE, subject TEXT, paper TEXT, weightage INTEGER DEFAULT 5
        );
        CREATE TABLE IF NOT EXISTS questions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            topic_id INTEGER REFERENCES topics(id),
            question_text TEXT, option_a TEXT, option_b TEXT, option_c TEXT, option_d TEXT,
            correct_option TEXT, explanation TEXT, difficulty TEXT DEFAULT 'medium',
            source TEXT, language TEXT DEFAULT 'bilingual'
        );
        CREATE TABLE IF NOT EXISTS mock_tests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            started_at TEXT, completed_at TEXT, paper TEXT, total_questions INTEGER,
            score REAL, max_score INTEGER, time_taken_sec INTEGER, status TEXT DEFAULT 'in_progress'
        );
        CREATE TABLE IF NOT EXISTS test_responses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            test_id INTEGER REFERENCES mock_tests(id),
            question_id INTEGER, selected_option TEXT, is_correct INTEGER,
            time_spent_sec REAL, confidence TEXT DEFAULT 'medium',
            error_type TEXT
        );
        CREATE TABLE IF NOT EXISTS error_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            test_id INTEGER REFERENCES mock_tests(id),
            question_id INTEGER, topic_id INTEGER REFERENCES topics(id),
            selected_option TEXT, correct_option TEXT, error_type TEXT,
            root_cause TEXT, resolved INTEGER DEFAULT 0, created_at TEXT,
            redo_1_score REAL, redo_2_score REAL
        );
        CREATE TABLE IF NOT EXISTS topic_mastery (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            topic_id INTEGER REFERENCES topics(id) UNIQUE,
            diagnostic_score REAL, current_score REAL, study_hours REAL DEFAULT 0,
            status TEXT DEFAULT 'not_started', last_studied TEXT, test_count INTEGER DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS study_sessions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT, topic_id INTEGER REFERENCES topics(id),
            duration_min INTEGER, mcqs_solved INTEGER, score REAL, notes TEXT
        );
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY, value TEXT
        );
        INSERT OR IGNORE INTO settings (key, value) VALUES ('target_score', '75');
        INSERT OR IGNORE INTO settings (key, value) VALUES ('accuracy_focus', 'true');
        INSERT OR IGNORE INTO settings (key, value) VALUES ('weakness_threshold', '60');

        CREATE TABLE IF NOT EXISTS doubt_cache (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            cache_key TEXT UNIQUE NOT NULL,
            response_json TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
    ''')
    db.commit()
    db.close()

# ─── Seed Data ────────────────────────────────────────────────
def seed_data():
    db = sqlite3.connect(DB_PATH)
    c = db.cursor()

    # Skip if questions already seeded
    existing = c.execute('SELECT COUNT(*) FROM questions').fetchone()[0]
    if existing > 0:
        db.close()
        return

    # Topics
    topics = [
        # Paper I Topics
        (1, 'Ancient Rajasthan', 'History', 'I', 5), (2, 'Rajput Dynasties', 'History', 'I', 12),
        (3, 'Mughal-Rajput Relations', 'History', 'I', 6), (4, 'Modern Rajasthan & Unification', 'History', 'I', 8),
        (5, 'Art Architecture & Culture', 'History', 'I', 10), (6, 'Folk Traditions', 'History', 'I', 7),
        (7, 'Physical Geography & Aravalli', 'Geography', 'I', 8), (8, 'Drainage System & Lakes', 'Geography', 'I', 10),
        (9, 'Climate & Soils', 'Geography', 'I', 5), (10, 'Mineral Resources & Mines', 'Geography', 'I', 8),
        (11, 'Agriculture & Irrigation', 'Geography', 'I', 7), (12, 'Wildlife & National Parks', 'Geography', 'I', 5),
        (13, 'Demographics & Tribes', 'Geography', 'I', 4), (14, 'Polity & Administration', 'Polity', 'I', 6),
        (15, 'Panchayati Raj & Local Governance', 'Polity', 'I', 5), (16, 'State Schemes & Budget', 'Polity', 'I', 5),
        (17, 'General Science - Biology', 'Science', 'I', 5), (18, 'General Science - Physics & Chemistry', 'Science', 'I', 5),
        (19, 'Current Affairs - Rajasthan', 'Current', 'I', 8), (20, 'Current Affairs - National', 'Current', 'I', 5),
        (21, 'Reasoning - Verbal', 'Reasoning', 'I', 7), (22, 'Reasoning - Non-Verbal', 'Reasoning', 'I', 5),
        (23, 'Quantitative Aptitude', 'Quant', 'I', 6), (24, 'Data Interpretation', 'Quant', 'I', 4),
        # Paper II Topics
        (25, 'Computer Fundamentals', 'CS', 'II', 10), (26, 'Number Systems', 'CS', 'II', 5),
        (27, 'MS Office Suite', 'CS', 'II', 8), (28, 'Programming C/C++', 'CS', 'II', 8),
        (29, 'OOP & Java', 'CS', 'II', 5), (30, 'Python Programming', 'CS', 'II', 4),
        (31, 'Data Structures', 'CS', 'II', 8), (32, 'Algorithms', 'CS', 'II', 5),
        (33, 'DBMS & SQL', 'CS', 'II', 10), (34, 'Operating System', 'CS', 'II', 8),
        (35, 'Computer Networks', 'CS', 'II', 8), (36, 'Network Security', 'CS', 'II', 5),
        (37, 'Web Technologies', 'CS', 'II', 5), (38, 'System Analysis & Design', 'CS', 'II', 4),
        (39, 'IoT & Emerging Tech', 'CS', 'II', 3), (40, 'Pedagogy & Teaching', 'CS', 'II', 5),
        (41, 'Computer Organization', 'CS', 'II', 5), (42, 'AI & Machine Learning', 'CS', 'II', 3),
    ]
    for t in topics:
        c.execute('INSERT OR IGNORE INTO topics (id, name, subject, paper, weightage) VALUES (?,?,?,?,?)', t)

    # Seed Questions — comprehensive question bank (208 questions across all 42 topics)
    qs = [
        (7, 'Which is the highest peak of the Aravalli range in Rajasthan?\\nराजस्थान में अरावली पर्वतमाला की सबसे ऊंची चोटी कौन सी है?', 'Guru Shikhar\\nगुरु शिखर', 'Ser\\nसेर', 'Jarga\\nजार्गा', 'Raghunathgarh\\nरघुनाथगढ़', 'A', 'Guru Shikhar (1,722 m) on Mount Abu in Sirohi district is the highest peak of the Aravalli range and also the highest point in Rajasthan. It is frequently asked in RPSC exams as a straightforward factual question.', 'medium', 'agent'),
        (7, 'The Aravalli range is an example of which type of mountain?\\nअरावली पर्वतमाला किस प्रकार के पर्वत का उदाहरण है?', 'Fold mountain\\nवलित पर्वत', 'Block mountain\\nब्लॉक पर्वत', 'Residual mountain\\nअवशिष्ट पर्वत', 'Volcanic mountain\\nज्वालामुखी पर्वत', 'C', 'The Aravalli range is one of the oldest mountain ranges in the world and is classified as a residual mountain range. Residual mountains are formed by the erosion of uplifted land, leaving behind hard rocks. RPSC 2nd Grade 2015 exam had this exact question.', 'medium', 'agent'),
        (7, 'Which is the second highest peak of the Aravalli range in Rajasthan?\\nराजस्थान में अरावली पर्वतमाला की दूसरी सबसे ऊंची चोटी कौन सी है?', 'Dilwara\\nदिलवाड़ा', 'Ser\\nसेर', 'Achalgarh\\nअचलगढ़', 'Jarga\\nजार्गा', 'B', 'Ser peak (1,597 m) located in Sirohi district is the second highest peak of the Aravalli range after Guru Shikhar. This is a commonly asked question in RPSC exams testing knowledge of peak height rankings.', 'hard', 'agent'),
        (7, 'Raghunathgarh, the highest peak of North-Eastern Aravalli, is located in which district?\\nरघुनाथगढ़, पूर्वोत्तर अरावली की सबसे ऊंची चोटी, किस जिले में स्थित है?', 'Ajmer\\nअजमेर', 'Sikar\\nसीकर', 'Alwar\\nअलवर', 'Jaipur\\nजयपुर', 'B', 'Raghunathgarh (1,055 m) is the highest peak in the North-Eastern Aravalli and is located in Sikar district. It is an important landmark in the Shekhawati region and frequently appears in RPSC geography questions.', 'hard', 'agent'),
        (7, 'Which of the following is a major pass in the Aravalli range of Rajasthan?\\nनिम्नलिखित में से कौन राजस्थान में अरावली पर्वतमाला का एक प्रमुख दर्रा है?', 'Nathula\\nनाथूला', 'Palghat\\nपालघाट', 'Dewair\\nदेवेयर', 'Shipki La\\nशिपकी ला', 'C', 'Dewair Pass (also called Desuri Pass) is a major pass in the Aravalli range connecting Pali and Udaipur districts. Other important Aravalli passes include Pipliya Ghat and Barr Pass. Nathula and Shipki La are in the Himalayas, and Palghat is in the Western Ghats.', 'medium', 'agent'),
        (8, 'Which is the only perennial river of Rajasthan?\\nराजस्थान की एकमात्र बारहमासी नदी कौन सी है?', 'Banas\\nबनास', 'Luni\\nलूणी', 'Chambal\\nचम्बल', 'Mahi\\nमही', 'C', 'The Chambal is the only perennial river in Rajasthan as it receives water throughout the year from the Vindhyan ranges and its tributaries. This was asked in RPSC 2nd Grade GK 2017 as an Assertion-Reason question.', 'easy', 'agent'),
        (8, 'Which is the largest saline lake in India, located in Rajasthan?\\nराजस्थान में स्थित भारत की सबसे बड़ी खारे पानी की झील कौन सी है?', 'Pachpadra Lake\\nपचपदरा झील', 'Didwana Lake\\nडीडवाना झील', 'Sambhar Lake\\nसांभर झील', 'Lunkaransar Lake\\nलूणकरणसर झील', 'C', "Sambhar Lake, located at the confluence of Jaipur, Ajmer and Nagaur districts, is India\\'s largest inland saline lake. It was designated as a Ramsar site in 1990 and is a major salt producer, contributing about 8% of India\\'s salt production.", 'easy', 'agent'),
        (8, 'Rajsamand Lake, after which the district is named, was built on which river?\\nराजसमंद झील, जिसके नाम पर जिले का नाम रखा गया है, किस नदी पर बनाई गई थी?', 'Banas\\nबनास', 'Gomti\\nगोमती', 'Chambal\\nचम्बल', 'Berach\\nबेड़च', 'B', 'Rajsamand Lake was built by Maharana Raj Singh in 1662 AD by damming the Gomti River. It is the second largest artificial lake in India and is the only lake in Rajasthan after which a district is named.', 'medium', 'agent'),
        (8, 'The Plain of Inland Drainage in Rajasthan is also known as which region?\\nराजस्थान में आंतरिक अपवाह का मैदान किस क्षेत्र के नाम से जाना जाता है?', 'Hadoti Region\\nहाड़ौती क्षेत्र', 'Mewar Region\\nमेवाड़ क्षेत्र', 'Shekhawati Region\\nशेखावाटी क्षेत्र', 'Marwar Region\\nमारवाड़ क्षेत्र', 'C', 'The Plain of Inland Drainage in Rajasthan is known as the Shekhawati Region. In this region, rivers do not flow into the sea but drain into inland lakes or evaporate. This was asked in RPSC EO-RO 2023 exam.', 'medium', 'agent'),
        (8, 'Which of the following districts is NOT benefitted by the Jawai project?\\nनिम्नलिखित में से कौन सा जिला जवाई परियोजना से लाभान्वित नहीं होता है?', 'Pali\\nपाली', 'Jalore\\nजालौर', 'Jodhpur\\nजोधपुर', 'Udaipur\\nउदयपुर', 'D', 'The Jawai project, built on the Jawai River, benefits Pali, Jalore and Jodhpur districts for irrigation and drinking water. Udaipur district is not a beneficiary of this project. This was asked in RPSC RAS Prelims 2013.', 'medium', 'agent'),
        (9, "According to Koppen\\'s climate classification, which climate type is found in Jaisalmer district?\\nकोपेन के जलवायु वर्गीकरण के अनुसार, जैसलमेर जिले में किस प्रकार की जलवायु पाई जाती है?", 'Aw\\nAw', 'BShw\\nBShw', 'BWhw\\nBWhw', 'Cwg\\nCwg', 'C', "Jaisalmer district falls under the BWhw (Hot Desert/Arid) climate type as per Koppen\\'s classification, with average annual rainfall below 20 cm. This is a standard RPSC question testing knowledge of Koppen climate zones in Rajasthan.", 'easy', 'agent'),
        (9, "As per Koppen\\'s classification, which region of Rajasthan experiences \\'Aw\\' type of climate?\\nकोपेन के वर्गीकरण के अनुसार, राजस्थान के किस क्षेत्र में \\'Aw\\' प्रकार की जलवायु पाई जाती है?", 'Western Rajasthan\\nपश्चिमी राजस्थान', 'Northern Rajasthan\\nउत्तरी राजस्थान', 'Southern Rajasthan\\nदक्षिणी राजस्थान', 'Eastern Rajasthan\\nपूर्वी राजस्थान', 'C', "The \\'Aw\\' (Tropical Humid/Savanna) climate type is found in southern Rajasthan covering districts like Banswara, Dungarpur, Jhalawar, Kota and Baran. These areas receive over 80 cm of rainfall annually. This was asked in RPSC Sr. Teacher 2022 exam.", 'medium', 'agent'),
        (9, 'Which soil type covers the largest geographical area in Rajasthan?\\nराजस्थान में सबसे अधिक भौगोलिक क्षेत्रफल पर कौन सी मिट्टी पाई जाती है?', 'Alluvial soil\\nजलोढ़ मिट्टी', 'Black soil\\nकाली मिट्टी', 'Desert soil\\nमरुस्थलीय मिट्टी', 'Red soil\\nलाल मिट्टी', 'C', "Desert soil (also called Bhur soil) covers approximately 62% of Rajasthan\\'s total area, making it the most extensive soil type. It is predominantly found in western Rajasthan districts like Jaisalmer, Barmer, Bikaner, and Jodhpur.", 'easy', 'agent'),
        (9, 'Black soil (Regur) in Rajasthan is predominantly found in which region?\\nराजस्थान में काली मिट्टी (रेगुर) मुख्यतः किस क्षेत्र में पाई जाती है?', 'Marwar region\\nमारवाड़ क्षेत्र', 'Hadoti region\\nहाड़ौती क्षेत्र', 'Mewar region\\nमेवाड़ क्षेत्र', 'Shekhawati region\\nशेखावाटी क्षेत्र', 'B', "Black soil (Regur) in Rajasthan is primarily found in the Hadoti region covering Kota, Bundi, Jhalawar and Baran districts. It covers only about 5% of the state\\'s area and is formed from weathering of Deccan Trap basalt rocks. It is ideal for cotton cultivation.", 'hard', 'agent'),
        (9, 'Which location in Rajasthan receives the highest average annual rainfall?\\nराजस्थान में सबसे अधिक औसत वार्षिक वर्षा कहाँ होती है?', 'Jhalawar\\nझालावाड़', 'Banswara\\nबांसवाड़ा', 'Mount Abu\\nमाउंट आबू', 'Kota\\nकोटा', 'C', 'Mount Abu in Sirohi district receives the highest average annual rainfall in Rajasthan at about 1,638 mm. Its elevation in the Aravalli range causes orographic precipitation. Among plains districts, Jhalawar and Banswara receive the highest rainfall.', 'medium', 'agent'),
        (12, 'Which national park in Rajasthan is a UNESCO World Heritage Site?\\nराजस्थान का कौन सा राष्ट्रीय उद्यान यूनेस्को विश्व धरोहर स्थल है?', 'Ranthambore National Park\\nरणथंभौर राष्ट्रीय उद्यान', 'Desert National Park\\nडेजर्ट राष्ट्रीय उद्यान', 'Keoladeo National Park\\nकेवलादेव राष्ट्रीय उद्यान', 'Mukundra Hills National Park\\nमुकुंद्रा हिल्स राष्ट्रीय उद्यान', 'C', 'Keoladeo Ghana National Park in Bharatpur was declared a UNESCO World Heritage Site in 1985. It is renowned for its avian biodiversity, hosting over 370 bird species including migratory birds like the Siberian crane.', 'easy', 'agent'),
        (12, 'Sariska National Park is located in which district of Rajasthan?\\nसरिस्का राष्ट्रीय उद्यान राजस्थान के किस जिले में स्थित है?', 'Sawai Madhopur\\nसवाई माधोपुर', 'Alwar\\nअलवर', 'Bharatpur\\nभरतपुर', 'Kota\\nकोटा', 'B', 'Sariska National Park is located in Alwar district. It was declared a wildlife sanctuary in 1955, became a tiger reserve in 1978 under Project Tiger, and was designated a national park in 1982.', 'easy', 'agent'),
        (12, 'The Great Indian Bustard (Godawan), the state bird of Rajasthan, is primarily found in which protected area?\\nराजस्थान के राज्य पक्षी ग्रेट इंडियन बस्टर्ड (गोड़ावण) मुख्यतः किस संरक्षित क्षेत्र में पाया जाता है?', 'Keoladeo National Park\\nकेवलादेव राष्ट्रीय उद्यान', 'Ranthambore National Park\\nरणथंभौर राष्ट्रीय उद्यान', 'Desert National Park\\nडेजर्ट राष्ट्रीय उद्यान', 'Sariska Tiger Reserve\\nसरिस्का टाइगर रिजर्व', 'C', "The Great Indian Bustard (Godawan), Rajasthan\\'s state bird, is critically endangered and mainly found in the Desert National Park near Jaisalmer. This park covers approximately 3,162 sq km of desert ecosystem.", 'medium', 'agent'),
        (12, 'Tal Chhapar Sanctuary in Rajasthan is famous for which animal?\\nराजस्थान में ताल छापर अभयारण्य किस जानवर के लिए प्रसिद्ध है?', 'Tiger\\nबाघ', 'Lion\\nशेर', 'Blackbuck\\nकाला हिरण', 'One-horned rhinoceros\\nएक सींग वाला गैंडा', 'C', "Tal Chhapar Sanctuary in Churu district is known as the Blackbuck Sanctuary. It hosts a large population of blackbuck (India\\'s fastest antelope) along with desert foxes and migratory birds like harriers.", 'medium', 'agent'),
        (12, 'In which year was Ranthambore declared a National Park?\\nरणथंभौर को किस वर्ष राष्ट्रीय उद्यान घोषित किया गया था?', '1973', '1980', '1982', '1955', 'B', "Ranthambore was declared a game sanctuary in 1955, became part of Project Tiger in 1973 (one of India\\'s first nine tiger reserves), and was finally declared a National Park in 1980. It is located in Sawai Madhopur district.", 'hard', 'agent'),
        (13, 'Which is the largest Scheduled Tribe in Rajasthan by population?\\nजनसंख्या की दृष्टि से राजस्थान की सबसे बड़ी अनुसूचित जनजाति कौन सी है?', 'Bhil\\nभील', 'Meena\\nमीणा', 'Garasia\\nगरासिया', 'Sahariya\\nसहरिया', 'B', 'Meena (Mina) is the largest Scheduled Tribe in Rajasthan, constituting approximately 53.5% of the total ST population of the state. They are mainly concentrated in eastern Rajasthan districts like Jaipur, Dausa, Alwar, Sawai Madhopur and Karauli.', 'easy', 'agent'),
        (13, 'Which tribe is the second largest in population in Rajasthan as per the 2011 census?\\n2011 की जनगणना के अनुसार राजस्थान में जनसंख्या की दृष्टि से दूसरी सबसे बड़ी जनजाति कौन सी है?', 'Garasia\\nगरासिया', 'Damor\\nडामोर', 'Bhil\\nभील', 'Kathodi\\nकठोड़ी', 'C', "Bhil is the second largest Scheduled Tribe in Rajasthan comprising about 39.5% of the total ST population. Together, Meena and Bhil account for approximately 93% of Rajasthan\\'s total tribal population.", 'easy', 'agent'),
        (13, 'Which district of Rajasthan has the highest percentage of Scheduled Tribe population as per the 2011 census?\\n2011 की जनगणना के अनुसार राजस्थान के किस जिले में अनुसूचित जनजाति की जनसंख्या का प्रतिशत सबसे अधिक है?', 'Dungarpur\\nडूंगरपुर', 'Banswara\\nबांसवाड़ा', 'Udaipur\\nउदयपुर', 'Pratapgarh\\nप्रतापगढ़', 'B', 'Banswara district has the highest percentage of ST population in Rajasthan at 72.3%, followed by Dungarpur at 65.1% and Udaipur at 47.9%. This was asked in RPSC RAS Prelims 2021.', 'medium', 'agent'),
        (13, 'Which tribe of Rajasthan is classified as a Particularly Vulnerable Tribal Group (PVTG)?\\nराजस्थान की कौन सी जनजाति विशेष रूप से कमजोर जनजातीय समूह (PVTG) के रूप में वर्गीकृत है?', 'Meena\\nमीणा', 'Bhil\\nभील', 'Sahariya\\nसहरिया', 'Garasia\\nगरासिया', 'C', 'Sahariya is the only Particularly Vulnerable Tribal Group (PVTG) in Rajasthan, concentrated mainly in Baran district (Shahabad and Kishanganj blocks) and parts of Sawai Madhopur. They face extreme poverty and low literacy levels.', 'hard', 'agent'),
        (13, 'The Kathodi tribe in Rajasthan is mainly concentrated in which district?\\nराजस्थान में कठोड़ी जनजाति मुख्यतः किस जिले में केंद्रित है?', 'Banswara\\nबांसवाड़ा', 'Baran\\nबारां', 'Udaipur\\nउदयपुर', 'Sirohi\\nसिरोही', 'C', 'The Kathodi tribe is mainly concentrated in Udaipur district, with about 52% of their population residing in Kotda, Jhadol and Sarada tehsils. They were originally brought from Maharashtra for catechu-making from Khair trees. This was asked in RPSC AEn GK 2013.', 'hard', 'agent'),
        (3, 'The Battle of Khanwa (1527) was fought between Babur and which Rajput ruler of Mewar?\\nखानवा का युद्ध (1527) बाबर और मेवाड़ के किस राजपूत शासक के बीच लड़ा गया था?', 'Rana Kumbha', 'Rana Sanga', 'Maharana Pratap', 'Rana Amar Singh', 'B', "Rana Sanga (Maharana Sangram Singh) led a large Rajput confederacy against Babur at Khanwa in 1527. Babur\\'s decisive victory using artillery consolidated Mughal power in North India. Rana Kumbha built the Vijay Stambh; Maharana Pratap fought at Haldighati (1576); Rana Amar Singh signed the 1615 treaty with Jahangir.", 'medium', 'agent'),
        (3, 'In the Battle of Haldighati (18 June 1576), who led the Mughal forces against Maharana Pratap?\\nहल्दीघाटी के युद्ध (18 जून 1576) में महाराणा प्रताप के विरुद्ध मुगल सेना का नेतृत्व किसने किया?', 'Asaf Khan', 'Raja Man Singh', 'Todar Mal', 'Birbal', 'B', "Raja Man Singh I of Amber (a Kachhwaha Rajput and one of Akbar\\'s Navratnas) led the Mughal army alongside Asaf Khan. The battle ended in a tactical Mughal victory, but Maharana Pratap escaped and continued guerrilla resistance. Todar Mal was sent to negotiate later; Birbal was Akbar\\'s courtier but not the commander.", 'medium', 'agent'),
        (3, 'The Treaty of 1615 between the Mughal Empire and Mewar was concluded during the reign of which Mughal emperor, and exempted the Rana from which obligation?\\nमुगल साम्राज्य और मेवाड़ के बीच 1615 की संधि किस मुगल सम्राट के शासनकाल में संपन्न हुई, और राणा को किस दायित्व से छूट दी गई?', 'Akbar — paying tribute', 'Jahangir — personal attendance at court', 'Shah Jahan — military service', 'Aurangzeb — ceding territory', 'B', 'The Treaty of 1615 was signed between Emperor Jahangir and Maharana Amar Singh I. Its unique provision exempted the Rana from personal attendance at the Mughal court — a privilege granted to no other Rajput ruler. Prince Karan Singh represented Mewar at court as a 5,000 mansabdar.', 'hard', 'agent'),
        (3, 'The Battle of Sumel-Giri (Sammel) in 1544 was fought between Sher Shah Suri and which Rathore ruler of Marwar?\\nसुमेल-गिरी (सम्मेल) का युद्ध 1544 में शेरशाह सूरी और मारवाड़ के किस राठौर शासक के बीच लड़ा गया था?', 'Rao Jodha', 'Rao Bika', 'Rao Maldeo', 'Rao Ganga', 'C', 'Rao Maldeo Rathore of Jodhpur fought Sher Shah Suri at Sumel-Giri in Pali district. Despite having only ~8,000 Rajputs against ~80,000 Afghans, they inflicted heavy casualties. Sher Shah famously remarked, "I would have lost the empire for a handful of millet." Rao Jodha founded Jodhpur (1459); Rao Bika founded Bikaner.', 'hard', 'agent'),
        (3, 'Who among the following Rajput rulers is credited with facilitating the entry of the Marathas into Rajasthan in the early 18th century?\\nनिम्नलिखित में से किस राजपूत शासक को 18वीं शताब्दी के प्रारंभ में राजस्थान में मराठों के प्रवेश का श्रेय दिया जाता है?', 'Sawai Jai Singh of Amber', 'Ratan Singh of Mewar', 'Abhay Singh of Marwar', 'Rao Buddh Singh of Bundi', 'D', 'Rao Buddh Singh of Bundi formed an alliance with the Marathas and invited them into Rajasthan to settle political scores. This opened the door for Maratha interference in Rajputana affairs, which continued throughout the 18th century. Sawai Jai Singh maintained diplomatic relations but did not initiate Maratha entry.', 'medium', 'agent'),
        (4, "In how many stages was the unification of Rajasthan completed after India\\'s independence?\\nस्वतंत्रता के बाद राजस्थान का एकीकरण कितने चरणों में पूरा हुआ?", 'Five', 'Six', 'Seven', 'Eight', 'C', 'The unification of Rajasthan was completed in seven stages, spanning from 18 March 1948 to 1 November 1956, taking a total of 8 years, 7 months, and 14 days. Sardar Vallabhbhai Patel and V.P. Menon were the chief architects of this integration.', 'easy', 'agent'),
        (4, 'Which of the following areas were merged into Rajasthan in the seventh and final stage of unification on 1 November 1956?\\n1 नवंबर 1956 को एकीकरण के सातवें एवं अंतिम चरण में निम्नलिखित में से कौन से क्षेत्र राजस्थान में शामिल किए गए?', 'Sirohi and Mount Abu', 'Ajmer-Merwara and Abu Road Taluka', 'Matsya Union and Kota', 'Jhalawar and Kishangarh', 'B', 'Under the States Reorganisation Act 1956, Ajmer-Merwara (Part C state), Abu Road Taluka (from Bombay state), and Sunel Tappa (from Madhya Bharat) were merged into Rajasthan. Sironj subdivision was transferred to Madhya Pradesh. Mohan Lal Sukhadia was the CM at this time.', 'hard', 'agent'),
        (5, 'The Ranakpur Jain Temple, built in 1437 under the patronage of Rana Kumbha, is famous for having how many uniquely carved marble pillars — none of which are identical?\\n1437 में राणा कुंभा के संरक्षण में निर्मित रणकपुर जैन मंदिर कितने अद्वितीय नक्काशीदार संगमरमर के स्तंभों के लिए प्रसिद्ध है — जिनमें से कोई भी दो समान नहीं हैं?', '1000', '1444', '1200', '1500', 'B', 'The Ranakpur Jain Temple (Pali district) has 1,444 uniquely carved marble pillars, 29 halls, and 80 domes. It was built by Seth Dharna Shah with architect Depaka. The Chaumukha (four-faced) idol of Adinath is the main deity. The pillars reportedly change colour throughout the day with sunlight.', 'medium', 'agent'),
        (5, 'The famous Dilwara Jain Temples, renowned for their exquisite marble carvings, are located at which place in Rajasthan?\\nअपनी उत्कृष्ट संगमरमर नक्काशी के लिए प्रसिद्ध दिलवाड़ा जैन मंदिर राजस्थान में किस स्थान पर स्थित हैं?', 'Ranakpur', 'Mount Abu', 'Bikaner', 'Jaisalmer', 'B', "The Dilwara Jain Temples are located on Mount Abu, Rajasthan\\'s only hill station. Built between the 11th and 13th centuries, the five marble temples were constructed by Vimal Shah (Vimal Vasahi, 1031 CE) and Vastupala-Tejapala (Luna Vasahi, 1230 CE). No cement was used — marble blocks are joined with interlocking joints.", 'easy', 'agent'),
        (5, 'The Vijay Stambh (Victory Tower) at Chittorgarh Fort was built by which ruler to commemorate his victory over Mahmud Khilji of Malwa?\\nचित्तौड़गढ़ किले में स्थित विजय स्तंभ का निर्माण किस शासक ने मालवा के महमूद खिलजी पर अपनी विजय के उपलक्ष्य में करवाया था?', 'Rana Sanga', 'Maharana Pratap', 'Rana Kumbha', 'Rana Amar Singh', 'C', 'Rana Kumbha (r. 1433-1468) built the 37-metre, 9-storey Vijay Stambh between 1440-1448 CE to commemorate his victory over Mahmud Khilji I of Malwa. The tower is dedicated to Lord Vishnu. In the same fort, the Kirti Stambh (Tower of Fame) was built earlier by a Jain merchant.', 'hard', 'agent'),
        (5, 'The Someshwar Temple at Kiradu and the Harshat Mata Temple at Abhaneri were built in which architectural style?\\nकिराडू का सोमेश्वर मंदिर और अभानेरी का हर्षत माता मंदिर किस वास्तुकला शैली में निर्मित हैं?', 'Nagara', 'Dravidian', 'Gurjar-Pratihara', 'Vesara', 'C', 'Both the Someshwar Temple (Kiradu, Barmer) and Harshat Mata Temple (Abhaneri, Dausa) are built in the Gurjar-Pratihara architectural style (8th-10th centuries CE). This style is characterized by a stepped platform, ornate pillars, and intricate carving. This question has appeared in RPSC 2nd Grade 2017 examination.', 'medium', 'agent'),
        (6, 'In which year was the Kalbeliya folk dance and songs of Rajasthan inscribed on the UNESCO Representative List of Intangible Cultural Heritage?\\nराजस्थान का कालबेलिया लोक नृत्य और गीत किस वर्ष यूनेस्को की अमूर्त सांस्कृतिक विरासत की प्रतिनिधि सूची में शामिल किया गया था?', '2005', '2008', '2010', '2012', 'C', "Kalbeliya dance (performed by the Kalbeliya snake-charmer community) was inscribed in 2010 as the first Rajasthani folk art on UNESCO\\'s Intangible Cultural Heritage list. The dance features serpentine movements, black swirling ghaghras, and is accompanied by the pungi (been), dufli, and khanjari.", 'medium', 'agent'),
        (6, 'The Gangaur festival, one of the most important festivals of Rajasthan, is celebrated in which Hindu calendar month?\\nराजस्थान के सबसे महत्वपूर्ण त्योहारों में से एक गणगौर त्योहार किस हिंदू कैलेंडर माह में मनाया जाता है?', 'Shravan', 'Bhadrapad', 'Chaitra', 'Kartik', 'C', 'Gangaur is celebrated in the month of Chaitra (March-April), starting from the day after Holi and lasting 18 days. It is dedicated to Goddess Gauri (Parvati) and Lord Shiva (Isar). Married and unmarried women pray for marital bliss and a good spouse. The grandest celebrations take place in Jaipur, Jodhpur, and Nathdwara.', 'easy', 'agent'),
        (6, 'The Terah Taali folk dance, in which 13 brass cymbals (manjeeras) are tied to the body and struck rhythmically, is performed by the Kamad tribe and dedicated to which folk deity?\\nतेरह ताली लोक नृत्य, जिसमें शरीर पर 13 पीतल की मंजीरा बांधकर लयबद्ध रूप से बजाए जाते हैं, कमाड़ जनजाति द्वारा किया जाता है और यह किस लोक देवता को समर्पित है?', 'Pabuji', 'Gogaji', 'Baba Ramdevji', 'Tejaji', 'C', 'Terah Taali is performed by women of the Kamad tribe (Pokhran and Nagaur region) sitting on the ground while striking 13 cymbals tied to their wrists, elbows, waist, and legs. It is a devotional dance dedicated to Baba Ramdevji (Ramdev Pir), a folk deity known for healing powers. The dance is also performed in Ramdevra temple.', 'hard', 'agent'),
        (31, 'In a stack, if elements are pushed in the order 1, 2, 3, 4, 5 and then POP operations are performed, what will be the sequence of popped elements?\\nस्टैक में, यदि तत्वों को 1, 2, 3, 4, 5 के क्रम में push किया जाए और फिर POP संक्रियाएं की जाएं, तो popped तत्वों का क्रम क्या होगा?', '1, 2, 3, 4, 5', '5, 4, 3, 2, 1', '1, 3, 5, 2, 4', '5, 1, 4, 2, 3', 'B', 'Stack follows the LIFO (Last In, First Out) principle. The last element pushed (5) is the first to be popped. So pop order is 5, 4, 3, 2, 1. स्टैक LIFO सिद्धांत का पालन करता है। सबसे अंत में pushed तत्व (5) सबसे पहले popped होता है।', 'easy', 'agent'),
        (31, 'Which of the following data structures is most suitable for implementing a circular buffer used in audio/video streaming?\\nऑडियो/वीडियो स्ट्रीमिंग में उपयोग होने वाले सर्कुलर बफर को लागू करने के लिए निम्नलिखित में से कौन सी डेटा संरचना सबसे उपयुक्त है?', 'Stack', 'Singly Linked List', 'Circular Queue', 'Binary Tree', 'C', 'A circular buffer is a fixed-size queue where the last element connects back to the first, forming a circle. Circular queue efficiently implements this with O(1) enqueue/dequeue operations. सर्कुलर बफर एक निश्चित आकार की कतार है जहां अंतिम तत्व पहले से जुड़ता है। सर्कुलर कतार इसे O(1) संक्रियाओं के साथ कुशलतापूर्वक लागू करती है।', 'easy', 'agent'),
        (31, 'In a doubly linked list, how many pointers need to be updated to delete a node from the middle (given the node to delete is pointed by ptr)?\\nदोहरी लिंक्ड सूची में, बीच से एक नोड को हटाने के लिए कितने पॉइंटर्स को अपडेट करने की आवश्यकता होती है (मान लें कि हटाए जाने वाले नोड को ptr द्वारा इंगित किया गया है)?', '1', '2', '3', '4', 'B', 'In a doubly linked list, to delete a middle node, we update ptr->prev->next = ptr->next and ptr->next->prev = ptr->prev. Two pointer updates are needed (excluding freeing memory). दोहरी लिंक्ड सूची में मध्य नोड हटाने के लिए दो पॉइंटर्स अपडेट करने होते हैं।', 'medium', 'agent'),
        (31, 'What is the maximum number of nodes in a complete binary tree of height h (where height is the number of levels starting from 1 at root)?\\nऊंचाई h (जहां ऊंचाई रूट से स्तरों की संख्या है, स्तर 1 से शुरू) के पूर्ण बाइनरी ट्री में नोड्स की अधिकतम संख्या क्या है?', '2^h - 1', '2^(h-1) - 1', '2^(h+1) - 1', '2^h', 'A', 'A complete/full binary tree of height h has maximum nodes = 2^h - 1. This is because level i (1-indexed) has at most 2^(i-1) nodes, and sum from i=1 to h of 2^(i-1) = 2^h - 1. ऊंचाई h के पूर्ण बाइनरी ट्री में अधिकतम नोड = 2^h - 1 होते हैं।', 'medium', 'agent'),
        (31, 'Which graph traversal algorithm uses a queue data structure for its implementation?\\nग्राफ ट्रैवर्सल का कौन सा एल्गोरिदम अपने कार्यान्वयन के लिए कतार डेटा संरचना का उपयोग करता है?', 'Depth First Search (DFS)', 'Breadth First Search (BFS)', "Dijkstra\\'s Algorithm", "Prim\\'s Algorithm", 'B', "BFS uses a queue to explore vertices level by level. It visits all neighbors of a vertex before moving to the next level. DFS uses a stack. Dijkstra\\'s uses a priority queue. BFS कतार का उपयोग करके स्तर दर स्तर शीर्षों का अन्वेषण करता है।", 'easy', 'agent'),
        (32, 'What is the time complexity of the binary search algorithm on a sorted array of n elements?\\nn तत्वों की क्रमबद्ध सरणी पर बाइनरी सर्च एल्गोरिदम की समय जटिलता क्या है?', 'O(n)', 'O(log n)', 'O(n^2)', 'O(n log n)', 'B', 'Binary search repeatedly divides the search interval in half. After each comparison, the search space halves. This gives O(log n) time complexity in the worst case. बाइनरी सर्च खोज अंतराल को बार-बार आधा करता है, जिससे सबसे खराब स्थिति में O(log n) समय जटिलता होती है।', 'easy', 'agent'),
        (32, 'Which of the following sorting algorithms has a worst-case time complexity of O(n^2) but works in O(n log n) on average?\\nनिम्नलिखित में से किस सॉर्टिंग एल्गोरिदम की सबसे खराब स्थिति में समय जटिलता O(n^2) है लेकिन औसतन O(n log n) पर काम करता है?', 'Merge Sort', 'Quick Sort', 'Bubble Sort', 'Radix Sort', 'B', 'Quick Sort has average-case O(n log n) but worst-case O(n^2) when the pivot is always the smallest or largest element. Merge Sort is O(n log n) in all cases. Bubble Sort is O(n^2) always. क्विक सॉर्ट की औसत जटिलता O(n log n) लेकिन सबसे खराब स्थिति O(n^2) है।', 'medium', 'agent'),
        (32, 'What is the time complexity of recursively computing the nth Fibonacci number using the simple recurrence F(n) = F(n-1) + F(n-2)?\\nसाधारण पुनरावृत्ति F(n) = F(n-1) + F(n-2) का उपयोग करके nवीं फाइबोनैचि संख्या की पुनरावर्ती गणना की समय जटिलता क्या है?', 'O(n)', 'O(log n)', 'O(2^n)', 'O(n^2)', 'C', 'The recurrence T(n) = T(n-1) + T(n-2) + O(1) solves to O(2^n). Each call branches into two recursive calls, creating an exponential tree of calls. This is why naive recursion is inefficient for Fibonacci. पुनरावृत्ति T(n) = T(n-1)+T(n-2)+O(1), O(2^n) होती है, जो अकुशल है।', 'medium', 'agent'),
        (32, 'Which algorithmic paradigm solves problems by breaking them into overlapping subproblems and storing their results to avoid redundant computations?\\nकौन सा एल्गोरिदमिक प्रतिमान समस्याओं को ओवरलैपिंग उप-समस्याओं में तोड़कर और पुनरावृत्त गणनाओं से बचने के लिए उनके परिणामों को संग्रहीत करके हल करता है?', 'Divide and Conquer', 'Greedy Algorithm', 'Dynamic Programming', 'Brute Force', 'C', 'Dynamic Programming stores results of overlapping subproblems (memoization or tabulation) to avoid recomputation. Divide and Conquer divides into non-overlapping subproblems. Greedy makes locally optimal choices. डायनामिक प्रोग्रामिंग ओवरलैपिंग उप-समस्याओं के परिणाम संग्रहीत कर पुनर्गणना से बचाती है।', 'medium', 'agent'),
        (32, 'If an algorithm has time complexity O(n^3), and it takes 1 second for n=100, approximately how long will it take for n=400?\\nयदि किसी एल्गोरिदम की समय जटिलता O(n^3) है, और n=100 के लिए इसे 1 सेकंड लगता है, तो n=400 के लिए लगभग कितना समय लगेगा?', '4 seconds', '16 seconds', '64 seconds', '256 seconds', 'C', 'When n increases by factor of 4 (400/100 = 4), O(n^3) runtime increases by factor of 4^3 = 64. So 1 second x 64 = 64 seconds. जब n 4 गुना बढ़ता है, O(n^3) रनटाइम 4^3 = 64 गुना बढ़ जाता है, अतः 1 सेकंड x 64 = 64 सेकंड।', 'hard', 'agent'),
        (33, 'Which normal form requires that every non-key attribute must be fully functionally dependent on the entire primary key (i.e., no partial dependencies)?\\nकिस सामान्य रूप में आवश्यक है कि प्रत्येक गैर-कुंजी विशेषता पूरी प्राथमिक कुंजी पर पूर्ण रूप से कार्यात्मक रूप से निर्भर हो (अर्थात कोई आंशिक निर्भरता नहीं)?', '1NF', '2NF', '3NF', 'BCNF', 'B', '2NF (Second Normal Form) eliminates partial dependencies. A table is in 2NF if it is in 1NF and every non-key attribute is fully functionally dependent on the entire primary key. 2NF आंशिक निर्भरताओं को समाप्त करता है। प्रत्येक गैर-कुंजी विशेषता पूरी प्राथमिक कुंजी पर निर्भर होनी चाहिए।', 'medium', 'agent'),
        (33, 'Consider two tables: Students(StudentID, Name) and Enrollments(StudentID, CourseID, Grade). Which SQL query will list the names of all students who have enrolled in at least one course?\\nदो तालिकाओं पर विचार करें: Students(StudentID, Name) और Enrollments(StudentID, CourseID, Grade)। कौन सा SQL क्वेरी उन सभी छात्रों के नाम सूचीबद्ध करेगा जिन्होंने कम से कम एक पाठ्यक्रम में नामांकन कराया है?', 'SELECT Name FROM Students WHERE StudentID IN (SELECT DISTINCT StudentID FROM Enrollments)', 'SELECT Name FROM Students, Enrollments', 'SELECT Name FROM Students WHERE StudentID = ANY Enrollments', 'SELECT Name FROM Students HAVING COUNT(StudentID) > 0', 'A', 'The subquery with IN clause selects StudentIDs from Enrollments table, and the outer query fetches names matching those IDs. Option B would produce a Cartesian product. Option D has incorrect HAVING without GROUP BY. सबक्वेरी IN खंड के साथ Enrollments से StudentID चुनती है और बाहरी क्वेरी संबंधित नाम लाती है।', 'medium', 'agent'),
        (33, 'In SQL, what is the difference between INNER JOIN and LEFT JOIN?\\nSQL में, INNER JOIN और LEFT JOIN के बीच क्या अंतर है?', 'INNER JOIN returns only matching rows; LEFT JOIN returns all rows from left table with NULL for non-matching right table rows', 'INNER JOIN is faster than LEFT JOIN always', 'LEFT JOIN returns only matching rows; INNER JOIN returns all rows', 'Both are identical in results', 'A', 'INNER JOIN returns rows only when there is a match in both tables. LEFT JOIN returns all rows from the left table; if no match in the right table, NULL values are filled. INNER JOIN केवल मेल खाने वाली पंक्तियाँ लौटाता है जबकि LEFT JOIN बाईं तालिका की सभी पंक्तियाँ लौटाता है।', 'easy', 'agent'),
        (33, 'Which ACID property ensures that a transaction is either executed completely or not at all?\\nACID का कौन सा गुण सुनिश्चित करता है कि लेन-देन या तो पूरी तरह से निष्पादित हो या बिल्कुल न हो?', 'Consistency', 'Isolation', 'Atomicity', 'Durability', 'C', 'Atomicity guarantees "all or nothing" — if any part of a transaction fails, the entire transaction is rolled back, leaving the database unchanged. Atomicity "सब या कुछ नहीं" सुनिश्चित करता है — यदि लेन-देन का कोई भाग विफल होता है, तो पूरा लेन-देन वापस लुढ़क जाता है।', 'easy', 'agent'),
        (33, 'A relation R is in BCNF if and only if for every non-trivial functional dependency X -> Y, which condition holds?\\nएक संबंध R, BCNF में होता है यदि और केवल यदि प्रत्येक गैर-तुच्छ कार्यात्मक निर्भरता X -> Y के लिए कौन सी शर्त लागू होती है?', 'X is a superkey', 'Y is a prime attribute', 'X is not a key', 'Y is a foreign key', 'A', 'BCNF (Boyce-Codd Normal Form) requires that for every non-trivial FD X -> Y, X must be a superkey. BCNF is stricter than 3NF. BCNF में प्रत्येक गैर-तुच्छ FD X -> Y के लिए X को एक सुपरकी होना आवश्यक है। BCNF, 3NF से अधिक कठोर है।', 'hard', 'agent'),
        (34, 'Which CPU scheduling algorithm is provably optimal in terms of minimizing the average waiting time (for non-preemptive case)?\\nऔसत प्रतीक्षा समय को न्यूनतम करने के संदर्भ में (गैर-पूर्व emptive मामले के लिए) कौन सा CPU शेड्यूलिंग एल्गोरिदम सर्वोत्तम सिद्ध है?', 'First Come First Served (FCFS)', 'Shortest Job First (SJF)', 'Round Robin (RR)', 'Priority Scheduling', 'B', 'SJF (non-preemptive) is proven to give the minimum average waiting time among all non-preemptive scheduling algorithms. It selects the process with the smallest CPU burst time. SJF (गैर-पूर्व emptive) सभी गैर-पूर्व emptive शेड्यूलिंग एल्गोरिदम के बीच न्यूनतम औसत प्रतीक्षा समय देता है।', 'medium', 'agent'),
        (34, 'Which of the following is NOT a necessary condition for deadlock to occur?\\nडेडलॉक होने के लिए निम्नलिखित में से कौन सी आवश्यक शर्त नहीं है?', 'Mutual Exclusion', 'Hold and Wait', 'Preemption', 'Circular Wait', 'C', 'The four necessary conditions for deadlock are: Mutual Exclusion, Hold and Wait, No Preemption, and Circular Wait. Preemption itself is NOT a condition — rather "No Preemption" is the condition. डेडलॉक की चार आवश्यक शर्तें हैं: Mutual Exclusion, Hold and Wait, No Preemption, और Circular Wait। Preemption स्वयं शर्त नहीं है।', 'medium', 'agent'),
        (34, 'In paged memory management, what is a "page fault"?\\nपेज्ड मेमोरी प्रबंधन में, "पेज फॉल्ट" क्या है?', 'An error in the page table', 'When a program accesses a page that is not currently in main memory', 'When two programs access the same page', 'When the page size is incorrect', 'B', 'A page fault occurs when a program attempts to access a memory page that is mapped in the virtual address space but is not currently loaded into physical RAM. The OS must load it from disk. पेज फॉल्ट तब होता है जब प्रोग्राम किसी ऐसे पेज तक पहुंचने का प्रयास करता है जो RAM में उपलब्ध नहीं है और डिस्क से लोड करना होता है।', 'easy', 'agent'),
        (34, 'Which page replacement algorithm suffers from "Belady\\\'s Anomaly" where increasing the number of page frames can increase the page fault rate?\\nकौन सा पेज रिप्लेसमेंट एल्गोरिदम "बेलाडी विसंगति" से ग्रस्त है जहां पेज फ्रेम की संख्या बढ़ाने से पेज फॉल्ट दर बढ़ सकती है?', 'Optimal Page Replacement', 'LRU (Least Recently Used)', 'FIFO (First In First Out)', 'LFU (Least Frequently Used)', 'C', "FIFO page replacement exhibits Belady\\'s Anomaly — under certain reference strings, adding more frames increases page faults. LRU and Optimal do not suffer from this anomaly. FIFO पेज रिप्लेसमेंट बेलाडी विसंगति प्रदर्शित करता है — कुछ संदर्भ स्ट्रिंग्स में अधिक फ्रेम जोड़ने से पेज फॉल्ट बढ़ जाते हैं।", 'hard', 'agent'),
        (34, 'In a UNIX/Linux file system, what information is stored in an inode?\\nUNIX/Linux फाइल सिस्टम में, inode में कौन सी जानकारी संग्रहीत होती है?', 'File name only', 'File metadata (permissions, size, timestamps, disk block pointers) but NOT the file name', 'The actual file content', 'The directory path', 'B', 'The inode stores metadata about a file: permissions, owner, size, timestamps, and pointers to disk blocks. The file name is stored in the directory entry, not the inode. inode फ़ाइल का मेटाडेटा संग्रहीत करता है: अनुमतियाँ, स्वामी, आकार, समय-चिह्न और डिस्क ब्लॉक पॉइंटर्स। फ़ाइल का नाम inode में नहीं बल्कि निर्देशिका प्रविष्टि में संग्रहीत होता है।', 'medium', 'agent'),
        (35, 'At which layer of the OSI model does a router primarily operate?\\nराउटर मुख्य रूप से OSI मॉडल की किस परत पर कार्य करता है?', 'Physical Layer', 'Data Link Layer', 'Network Layer', 'Transport Layer', 'C', 'A router operates at the Network Layer (Layer 3) of the OSI model. It uses IP addresses to determine the best path for forwarding packets between different networks. राउटर OSI मॉडल के नेटवर्क लेयर (लेयर 3) पर कार्य करता है और IP पतों का उपयोग करके पैकेट को अग्रेषित करता है।', 'easy', 'agent'),
        (35, 'Which protocol in the TCP/IP suite is responsible for resolving IP addresses to MAC addresses?\\nTCP/IP सूट में कौन सा प्रोटोकॉल IP पतों को MAC पतों में हल करने के लिए जिम्मेदार है?', 'DNS', 'ARP', 'DHCP', 'ICMP', 'B', 'ARP (Address Resolution Protocol) resolves an IP address to its corresponding MAC (physical) address on a local network. DNS resolves domain names to IP addresses. ARP (Address Resolution Protocol) एक IP पते को स्थानीय नेटवर्क पर उसके MAC पते में हल करता है।', 'medium', 'agent'),
        (35, 'What is the subnet mask for a Class C IP address by default?\\nक्लास C IP पते के लिए डिफ़ॉल्ट सबनेट मास्क क्या है?', '255.0.0.0', '255.255.0.0', '255.255.255.0', '255.255.255.255', 'C', 'Class C IP addresses (192.0.0.0 to 223.255.255.255) have a default subnet mask of 255.255.255.0, with 24 bits for the network portion and 8 bits for hosts. क्लास C IP पतों (192.0.0.0 से 223.255.255.255) का डिफ़ॉल्ट सबनेट मास्क 255.255.255.0 है, जिसमें 24 बिट नेटवर्क के लिए और 8 बिट होस्ट के लिए हैं।', 'medium', 'agent'),
        (35, 'Which transport layer protocol is connection-oriented and guarantees reliable delivery?\\nकौन सा ट्रांसपोर्ट लेयर प्रोटोकॉल कनेक्शन-उन्मुख है और विश्वसनीय वितरण की गारंटी देता है?', 'UDP', 'IP', 'TCP', 'HTTP', 'C', 'TCP (Transmission Control Protocol) is connection-oriented, uses three-way handshake, provides error checking, flow control, and guarantees reliable, ordered delivery of data. TCP कनेक्शन-उन्मुख है, त्रि-चरणीय हैंडशेक का उपयोग करता है, और विश्वसनीय, क्रमबद्ध डेटा वितरण सुनिश्चित करता है।', 'easy', 'agent'),
        (35, 'Which network topology has the highest fault tolerance because every node is connected to every other node?\\nकौन सी नेटवर्क टोपोलॉजी में सबसे अधिक दोष सहनशीलता होती है क्योंकि प्रत्येक नोड हर दूसरे नोड से जुड़ा होता है?', 'Star Topology', 'Bus Topology', 'Ring Topology', 'Mesh Topology', 'D', 'In a fully connected mesh topology, every node has a direct point-to-point link to every other node. This provides maximum fault tolerance because a link failure does not isolate any node. मेश टोपोलॉजी में प्रत्येक नोड का हर दूसरे नोड से सीधा संबंध होता है, जो अधिकतम दोष सहनशीलता प्रदान करता है।', 'easy', 'agent'),
        (36, 'Which type of encryption uses two keys — a public key for encryption and a private key for decryption?\\nकिस प्रकार का एन्क्रिप्शन दो कुंजियों का उपयोग करता है — एक सार्वजनिक कुंजी एन्क्रिप्शन के लिए और एक निजी कुंजी डिक्रिप्शन के लिए?', 'Symmetric Encryption', 'Asymmetric Encryption', 'Hashing', 'Base64 Encoding', 'B', 'Asymmetric encryption (also called public-key cryptography) uses a pair of keys: a public key for encryption and a private key for decryption. RSA is a common example. Symmetric encryption uses the same key for both. असममित एन्क्रिप्शन (सार्वजनिक-कुंजी क्रिप्टोग्राफी) एन्क्रिप्शन के लिए सार्वजनिक कुंजी और डिक्रिप्शन के लिए निजी कुंजी का उपयोग करती है।', 'easy', 'agent'),
        (36, 'Which type of firewall filters traffic based on source/destination IP addresses and port numbers without examining the packet payload?\\nकिस प्रकार का फायरवॉल पैकेट पेलोड की जांच किए बिना स्रोत/गंतव्य IP पतों और पोर्ट नंबरों के आधार पर ट्रैफिक को फ़िल्टर करता है?', 'Application-level Gateway', 'Packet Filtering Firewall', 'Stateful Inspection Firewall', 'Proxy Firewall', 'B', 'A Packet Filtering Firewall (stateless) examines only packet headers — source/destination IP, port numbers, and protocol. It does not inspect the payload or maintain connection state. पैकेट फ़िल्टरिंग फायरवॉल केवल हेडर्स की जांच करता है — स्रोत/गंतव्य IP, पोर्ट नंबर — पेलोड की जांच नहीं करता।', 'medium', 'agent'),
        (36, 'What is the primary difference between a virus and a worm?\\nवायरस और वर्म के बीच मुख्य अंतर क्या है?', 'A virus needs a host program to attach to and human action to spread; a worm is self-contained and spreads automatically', 'A worm needs a host program; a virus is self-contained', 'Both are identical', 'A virus spreads over networks; a worm spreads via USB drives', 'A', 'A virus attaches itself to a host program and requires human action (e.g., opening a file) to spread. A worm is a standalone program that replicates itself automatically across networks without human intervention. वायरस को फैलने के लिए होस्ट प्रोग्राम और मानव क्रिया की आवश्यकता होती है; वर्म स्वचालित रूप से नेटवर्क पर फैलता है।', 'easy', 'agent'),
        (36, 'In SSL/TLS, what is the purpose of the certificate authority (CA)?\\nSSL/TLS में, प्रमाणपत्र प्राधिकरण (CA) का उद्देश्य क्या है?', 'To encrypt all data transmitted between client and server', 'To digitally sign certificates to verify the identity of a website/server', 'To assign IP addresses to websites', 'To manage firewall rules', 'B', 'A Certificate Authority (CA) is a trusted entity that issues and digitally signs digital certificates. The signature verifies that the public key belongs to the claimed website/server, preventing man-in-the-middle attacks. प्रमाणपत्र प्राधिकरण विश्वसनीय इकाई है जो डिजिटल प्रमाणपत्र जारी और हस्ताक्षरित करता है, सर्वर की पहचान सत्यापित करता है।', 'medium', 'agent'),
        (36, 'Which authentication method requires the user to provide two different types of evidence from distinct categories (e.g., password + fingerprint)?\\nकौन सी प्रमाणीकरण विधि में उपयोगकर्ता को विभिन्न श्रेणियों से दो प्रकार के साक्ष्य प्रदान करने होते हैं (जैसे पासवर्ड + फिंगरप्रिंट)?', 'Single-Factor Authentication', 'Multi-Factor Authentication (MFA)', 'Single Sign-On (SSO)', 'Biometric Authentication', 'B', 'Multi-Factor Authentication requires at least two factors from different categories: something you know (password), something you have (token), and something you are (biometric). SSO is not the same as MFA. मल्टी-फैक्टर प्रमाणीकरण में विभिन्न श्रेणियों से कम से कम दो कारकों की आवश्यकता होती है।', 'medium', 'agent'),
        (37, 'Which HTML5 element is used to define navigation links in a semantically meaningful way?\\nनेविगेशन लिंक को अर्थपूर्ण रूप से परिभाषित करने के लिए किस HTML5 तत्व का उपयोग किया जाता है?', '<navigation>', '<nav>', '<navigate>', '<menu>', 'B', 'The HTML5 <nav> element is a semantic element that represents a section of a page intended for navigation links. It helps search engines and assistive technologies understand page structure. HTML5 का <nav> तत्व नेविगेशन लिंक के लिए एक अर्थपूर्ण तत्व है।', 'easy', 'agent'),
        (37, 'In CSS, what is the correct order of the Box Model from inside to outside?\\nCSS में, बॉक्स मॉडल का अंदर से बाहर तक सही क्रम क्या है?', 'Content -> Padding -> Border -> Margin', 'Content -> Margin -> Border -> Padding', 'Padding -> Content -> Border -> Margin', 'Margin -> Border -> Padding -> Content', 'A', 'The CSS Box Model from inside to outside is: Content (actual content area) -> Padding (space around content) -> Border (border around padding) -> Margin (space outside the border). CSS बॉक्स मॉडल अंदर से बाहर: Content -> Padding -> Border -> Margin।', 'medium', 'agent'),
        (37, 'In JavaScript, what is the difference between "==" and "===" operators?\\nजावास्क्रिप्ट में, "==" और "===" ऑपरेटरों के बीच क्या अंतर है?', 'Both are identical', '"==" compares values with type coercion; "===" compares both value and type without coercion', '"===" compares values with coercion; "==" compares without coercion', '"==" is used for numbers only', 'B', 'The "==" operator performs type coercion before comparison (e.g., 5 == "5" is true). The "===" operator (strict equality) compares both value and type without coercion (5 === "5" is false). "==" टाइप कोएर्शन के साथ मानों की तुलना करता है; "===" बिना कोएर्शन के मान और प्रकार दोनों की तुलना करता है।', 'medium', 'agent'),
        (37, 'What is the correct XML declaration syntax?\\nसही XML घोषणा सिंटैक्स क्या है?', '<xml version="1.0">', '<?xml version="1.0"?>', '<xml version="1.0"/>', '<!--xml version="1.0"-->', 'B', 'The XML declaration begins with "<?xml" and ends with "?>". It typically includes the version attribute: <?xml version="1.0"?>. This is not an XML element but a processing instruction. XML घोषणा "<?xml" से शुरू होती है और "?>" पर समाप्त होती है, जैसे <?xml version="1.0"?>।', 'easy', 'agent'),
        (37, 'Which HTTP method is considered safe and idempotent, typically used to retrieve a resource without modifying it?\\nकौन सी HTTP विधि सुरक्षित और idempotent मानी जाती है, जिसका उपयोग आमतौर पर संसाधन को संशोधित किए बिना प्राप्त करने के लिए किया जाता है?', 'POST', 'PUT', 'DELETE', 'GET', 'D', 'GET is safe (does not modify the resource) and idempotent (multiple identical requests have the same effect as a single request). POST is neither safe nor idempotent. GET सुरक्षित और idempotent है — यह संसाधन को संशोधित किए बिना केवल डेटा प्राप्त करता है।', 'easy', 'agent'),
        (38, 'Which SDLC model is characterized by sequential phases where each phase must be completed before the next begins?\\nकौन सा SDLC मॉडल अनुक्रमिक चरणों द्वारा विशेषता है जहां प्रत्येक चरण अगले शुरू होने से पहले पूरा होना चाहिए?', 'Spiral Model', 'Waterfall Model', 'Agile Model', 'V-Model', 'B', 'The Waterfall Model is a linear sequential model where each phase (Requirements -> Design -> Implementation -> Testing -> Deployment -> Maintenance) must be fully completed before the next phase begins. वॉटरफॉल मॉडल एक रैखिक अनुक्रमिक मॉडल है जहां प्रत्येक चरण अगले से पहले पूरी तरह पूरा होना चाहिए।', 'easy', 'agent'),
        (38, 'In a Data Flow Diagram (DFD), what do rectangles (or rounded rectangles) typically represent?\\nडेटा फ्लो आरेख (DFD) में, आयताकार (या गोल कोनों वाले आयत) आमतौर पर क्या दर्शाते हैं?', 'Data Store', 'External Entity', 'Process', 'Data Flow', 'B', 'In DFDs, rectangles represent external entities (also called terminators or sources/sinks) — systems or people outside the system boundary that interact with the system. Processes are circles/rounded rectangles, data stores are open rectangles. DFD में आयत बाहरी संस्थाओं को दर्शाते हैं — सिस्टम के बाहर के तत्व जो सिस्टम के साथ संवाद करते हैं।', 'medium', 'agent'),
        (38, 'In an ER diagram, what does a diamond shape represent?\\nER आरेख में, हीरे की आकृति क्या दर्शाती है?', 'Entity', 'Attribute', 'Relationship', 'Primary Key', 'C', 'In ER diagrams, a diamond shape represents a relationship between entities. Rectangles represent entities, ovals represent attributes, and underlined attributes represent primary keys. ER आरेख में हीरे की आकृति संस्थाओं के बीच संबंध (relationship) को दर्शाती है।', 'easy', 'agent'),
        (38, 'Which testing technique checks the internal structure, design, and code of the software rather than its external functionality?\\nकौन सी परीक्षण तकनीक सॉफ्टवेयर की बाहरी कार्यक्षमता के बजाय उसकी आंतरिक संरचना, डिजाइन और कोड की जांच करती है?', 'Black-Box Testing', 'White-Box Testing', 'Acceptance Testing', 'Alpha Testing', 'B', 'White-Box Testing (also called structural/glass-box testing) examines the internal logic, code paths, and structure of the software. It requires knowledge of the code implementation. Black-Box tests only functionality without internal knowledge. व्हाइट-बॉक्स परीक्षण आंतरिक कोड संरचना और तर्क की जांच करता है, जबकि ब्लैक-बॉक्स केवल बाहरी कार्यक्षमता का परीक्षण करता है।', 'medium', 'agent'),
        (38, 'Which Agile framework uses fixed-length iterations called "sprints" and includes roles such as Scrum Master and Product Owner?\\nकौन सा Agile ढांचा "स्प्रिंट" नामक निश्चित-अवधि के पुनरावृत्तियों का उपयोग करता है और इसमें स्क्रम मास्टर और प्रोडक्ट ओनर जैसी भूमिकाएं शामिल हैं?', 'Kanban', 'Extreme Programming (XP)', 'Scrum', 'Lean Software Development', 'C', 'Scrum is an Agile framework using fixed-length sprints (typically 1-4 weeks). Key roles include Scrum Master (facilitator), Product Owner (prioritizes backlog), and Development Team. Daily stand-up meetings are also characteristic. स्क्रम Agile ढांचा है जो निश्चित-अवधि के स्प्रिंट और स्क्रम मास्टर, प्रोडक्ट ओनर जैसी भूमिकाओं का उपयोग करता है।', 'medium', 'agent'),
        (39, 'Which layer in the typical IoT architecture is responsible for data acquisition from the physical world?\\nसामान्य IoT आर्किटेक्चर में कौन सी परत भौतिक दुनिया से डेटा अधिग्रहण के लिए जिम्मेदार है?', 'Network Layer', 'Application Layer', 'Perception/Sensing Layer', 'Middleware Layer', 'C', 'The Perception Layer (or Sensing Layer) is the physical layer of IoT architecture. It consists of sensors and actuators that interact with the physical environment to collect data. The Network Layer handles data transmission. पर्सेप्शन लेयर IoT आर्किटेक्चर की भौतिक परत है जिसमें सेंसर और एक्चुएटर शामिल हैं।', 'medium', 'agent'),
        (39, 'What is the primary function of an actuator in an IoT system?\\nIoT सिस्टम में एक्चुएटर का प्राथमिक कार्य क्या है?', 'To collect environmental data', 'To convert physical signals into electrical signals', 'To convert electrical signals into physical action/movement', 'To store data in the cloud', 'C', 'An actuator receives electrical signals (from a controller) and converts them into physical action such as movement, opening a valve, turning on a light, etc. Sensors do the opposite — they measure physical quantities. एक्चुएटर विद्युत संकेतों को भौतिक क्रिया में परिवर्तित करता है, जैसे वाल्व खोलना या लाइट चालू करना।', 'easy', 'agent'),
        (39, 'Which cloud service model provides the consumer with the ability to deploy and run software on a managed platform without managing the underlying infrastructure (OS, servers, storage)?\\nकौन सा क्लाउड सेवा मॉडल उपभोक्ता को अंतर्निहित बुनियादी ढांचे (OS, सर्वर, स्टोरेज) के प्रबंधन के बिना एक प्रबंधित प्लेटफॉर्म पर सॉफ्टवेयर तैनात करने की क्षमता प्रदान करता है?', 'Infrastructure as a Service (IaaS)', 'Platform as a Service (PaaS)', 'Software as a Service (SaaS)', 'Function as a Service (FaaS)', 'B', 'PaaS provides a managed platform including OS, runtime, and middleware. Users deploy their applications without managing the underlying infrastructure. IaaS provides virtual machines/storage. SaaS provides ready-to-use applications. PaaS एक प्रबंधित प्लेटफॉर्म प्रदान करता है जहां उपयोगकर्ता बुनियादी ढांचे के प्रबंधन के बिना एप्लिकेशन तैनात कर सकते हैं।', 'medium', 'agent'),
        (39, 'Which property of blockchain ensures that once a block is added to the chain, it cannot be altered retroactively?\\nब्लॉकचेन की कौन सी संपत्ति सुनिश्चित करती है कि एक बार श्रृंखला में ब्लॉक जुड़ जाने के बाद उसे पूर्वव्यापी रूप से नहीं बदला जा सकता?', 'Decentralization', 'Immutability', 'Consensus', 'Transparency', 'B', 'Immutability means that once data is recorded in a blockchain, it cannot be changed or deleted. This is achieved through cryptographic hashing — each block contains the hash of the previous block, creating a tamper-evident chain. इम्यूटेबिलिटी का अर्थ है कि ब्लॉकचेन में दर्ज डेटा को बदला या हटाया नहीं जा सकता, जो क्रिप्टोग्राफिक हैशिंग द्वारा प्राप्त होता है।', 'hard', 'agent'),
        (39, 'Which lightweight messaging protocol is commonly used in IoT for communication between devices due to its low bandwidth and publish-subscribe model?\\nIoT में उपकरणों के बीच संचार के लिए अपनी कम बैंडविड्थ और प्रकाशन-सदस्यता मॉडल के कारण आमतौर पर किस लाइटवेट मैसेजिंग प्रोटोकॉल का उपयोग किया जाता है?', 'HTTP', 'FTP', 'MQTT', 'SMTP', 'C', 'MQTT (Message Queuing Telemetry Transport) is a lightweight publish-subscribe messaging protocol designed for constrained devices and low-bandwidth, high-latency networks. It is ideal for IoT applications due to minimal code footprint and low power consumption. MQTT एक लाइटवेट publish-subscribe प्रोटोकॉल है जो IoT उपकरणों के लिए आदर्श है।', 'medium', 'agent'),
        (40, 'Which teaching method involves the teacher presenting information in a structured manner to a large group of students, with minimal student interaction?\\nकौन सी शिक्षण विधि में शिक्षक न्यूनतम छात्र सहभागिता के साथ बड़े समूह को संरचित तरीके से जानकारी प्रस्तुत करता है?', 'Discussion Method', 'Lecture Method', 'Demonstration Method', 'Project Method', 'B', 'The Lecture Method is a teacher-centered approach where the instructor delivers content orally to a large group. Students are primarily passive listeners with limited interaction. It is efficient for covering large amounts of content but offers limited engagement. व्याख्यान विधि एक शिक्षक-केंद्रित दृष्टिकोण है जहां शिक्षक बड़े समूह को मौखिक रूप से सामग्री प्रस्तुत करता है।', 'easy', 'agent'),
        (40, "According to Bloom\\'s Taxonomy (revised version), which is the highest level of cognitive learning?\\nब्लूम के वर्गीकरण (संशोधित संस्करण) के अनुसार, संज्ञानात्मक अधिगम का उच्चतम स्तर कौन सा है?", 'Evaluation', 'Synthesis', 'Creating', 'Analyzing', 'C', 'The revised Bloom\\\'s Taxonomy (Anderson & Krathwohl, 2001) has six levels from lowest to highest: Remember, Understand, Apply, Analyze, Evaluate, Create. "Create" (generating new ideas/products) replaced "Synthesis" as the highest level. संशोधित ब्लूम वर्गीकरण में उच्चतम स्तर "Create" (सृजन) है, जो नए विचारों/उत्पादों को उत्पन्न करने से संबंधित है।', 'medium', 'agent'),
        (40, 'Which type of assessment is conducted during the learning process to provide ongoing feedback and improve student learning?\\nकिस प्रकार का मूल्यांकन अधिगम प्रक्रिया के दौरान निरंतर प्रतिक्रिया प्रदान करने और छात्र अधिगम में सुधार करने के लिए किया जाता है?', 'Summative Assessment', 'Diagnostic Assessment', 'Formative Assessment', 'Placement Assessment', 'C', 'Formative Assessment is conducted during instruction to monitor student learning and provide ongoing feedback. It helps teachers adjust teaching strategies and helps students identify their strengths/weaknesses. Examples: quizzes, class discussions, exit tickets. रचनात्मक मूल्यांकन निर्देश के दौरान किया जाता है ताकि निरंतर प्रतिक्रिया प्रदान की जा सके और अधिगम में सुधार किया जा सके।', 'easy', 'agent'),
        (40, 'In lesson planning, what does the "anticipatory set" refer to?\\nपाठ योजना में, "anticipatory set" किसे संदर्भित करता है?', 'The homework assignment given at the end', "The hook or opening activity designed to grab students\\' attention and connect prior knowledge to new learning", 'The set of questions for the final exam', 'The seating arrangement of students', 'B', 'The anticipatory set (or "hook") is a brief opening activity at the beginning of a lesson designed to engage students, activate prior knowledge, and set the stage for new learning. It is a key component of Madeline Hunter\\\'s lesson plan model. एंटिसिपेटरी सेट पाठ की शुरुआत में एक संक्षिप्त गतिविधि है जो छात्रों का ध्यान आकर्षित करती है और पूर्व ज्ञान को सक्रिय करती है।', 'medium', 'agent'),
        (40, "Which learning theory emphasizes learning through observation and imitation of others, as demonstrated in Bandura\\'s Bobo doll experiment?\\nकौन सा अधिगम सिद्धांत दूसरों के अवलोकन और अनुकरण के माध्यम से अधिगम पर जोर देता है, जैसा कि बंडुरा के बोबो गुड़िया प्रयोग में प्रदर्शित किया गया?", 'Behaviorism', 'Cognitivism', 'Constructivism', 'Social Learning Theory', 'D', "Bandura\\'s Social Learning Theory posits that people learn by observing others (models). The Bobo doll experiment showed children imitating aggressive behavior they observed in adults. Key concepts: attention, retention, reproduction, and motivation. बंडुरा का सामाजिक अधिगम सिद्धांत बताता है कि लोग दूसरों के अवलोकन और अनुकरण से सीखते हैं।", 'hard', 'agent'),
        (41, 'Which CPU component is responsible for performing arithmetic and logical operations?\\nCPU का कौन सा घटक अंकगणितीय और तार्किक संक्रियाएं करने के लिए जिम्मेदार है?', 'Control Unit (CU)', 'Arithmetic Logic Unit (ALU)', 'Memory Management Unit (MMU)', 'Program Counter (PC)', 'B', 'The ALU (Arithmetic Logic Unit) performs all arithmetic operations (addition, subtraction, multiplication, division) and logical operations (AND, OR, NOT, XOR). The Control Unit coordinates operations but does not perform calculations. ALU सभी अंकगणितीय और तार्किक संक्रियाएं करता है।', 'easy', 'agent'),
        (41, 'Which addressing mode specifies the operand itself directly in the instruction, rather than its address?\\nकौन सा एड्रेसिंग मोड निर्देश में पते के बजाय सीधे ऑपरेंड को ही निर्दिष्ट करता है?', 'Direct Addressing', 'Indirect Addressing', 'Immediate Addressing', 'Register Addressing', 'C', 'Immediate Addressing mode: the operand value is part of the instruction itself (e.g., MOV R1, #5 — the value 5 is in the instruction). No memory reference is needed to fetch the operand. Direct Addressing refers to the memory address of the operand. इमीडिएट एड्रेसिंग में ऑपरेंड का मान सीधे निर्देश में ही होता है।', 'medium', 'agent'),
        (41, 'In a direct-mapped cache with 64 blocks and a main memory of 4096 blocks, which cache block does main memory block 250 map to?\\n64 ब्लॉक वाली डायरेक्ट-मैप्ड कैश में, में 4096 ब्लॉक वाली मुख्य मेमोरी में ब्लॉक 250 किस कैश ब्लॉक पर मैप होगा?', '122', '58', '250', '186', 'B', 'In direct-mapped cache, main memory block i maps to cache block (i mod number_of_cache_blocks). So 250 mod 64 = 250 - (3*64) = 250 - 192 = 58. ब्लॉक i कैश ब्लॉक (i mod कैश_ब्लॉक_संख्या) पर मैप होता है। 250 mod 64 = 58।', 'hard', 'agent'),
        (41, 'What is the primary advantage of pipelining in a processor?\\nप्रोसेसर में पाइपलाइनिंग का प्राथमिक लाभ क्या है?', 'It reduces the execution time of a single instruction', 'It increases throughput by overlapping the execution of multiple instructions', 'It reduces power consumption', 'It simplifies the control unit design', 'B', 'Pipelining increases instruction throughput (number of instructions completed per unit of time) by overlapping the execution of multiple instructions at different stages. It does NOT reduce the latency of a single instruction. पाइपलाइनिंग कई निर्देशों के निष्पादन को ओवरलैप करके थ्रूपुट बढ़ाती है, लेकिन एकल निर्देश का विलंब कम नहीं करती।', 'medium', 'agent'),
        (41, 'Which bus in a computer system is responsible for carrying data between the CPU, memory, and I/O devices?\\nकंप्यूटर सिस्टम में कौन सी बस CPU, मेमोरी और I/O उपकरणों के बीच डेटा ले जाने के लिए जिम्मेदार है?', 'Address Bus', 'Control Bus', 'Data Bus', 'System Bus', 'C', 'The Data Bus carries the actual data being transferred between components. It is bidirectional. The Address Bus carries memory addresses (unidirectional from CPU). The Control Bus carries control signals. डेटा बस घटकों के बीच वास्तविक डेटा ले जाती है और द्विदिशीय होती है।', 'medium', 'agent'),
        (42, 'Which type of machine learning uses labeled training data to learn a mapping from inputs to outputs?\\nकिस प्रकार की मशीन लर्निंग इनपुट से आउटपुट में मैपिंग सीखने के लिए लेबल किए गए प्रशिक्षण डेटा का उपयोग करती है?', 'Unsupervised Learning', 'Reinforcement Learning', 'Supervised Learning', 'Semi-supervised Learning', 'C', 'Supervised Learning learns a function that maps inputs to outputs using labeled training data (input-output pairs). Examples: classification (spam detection) and regression (price prediction). Unsupervised learning uses unlabeled data. पर्यवेक्षित अधिगम लेबल किए गए डेटा का उपयोग करके इनपुट-आउटपुट मैपिंग सीखता है।', 'easy', 'agent'),
        (42, 'What is a perceptron in the context of neural networks?\\nतंत्रिका नेटवर्क के संदर्भ में परसेप्ट्रॉन क्या है?', 'A multi-layer neural network', 'A single-layer binary linear classifier that computes a weighted sum of inputs and applies an activation function', 'A type of recurrent neural network', 'An unsupervised clustering algorithm', 'B', 'A perceptron is the simplest type of artificial neural network — a single-layer binary classifier. It computes a weighted sum of inputs, adds a bias, and passes the result through an activation function (typically step function) to produce a binary output. परसेप्ट्रॉन सबसे सरल कृत्रिम तंत्रिका नेटवर्क है — एक एकल-परत द्विआधारी रैखिक वर्गीकारक।', 'medium', 'agent'),
        (42, 'Which Natural Language Processing (NLP) task involves determining the emotional tone or sentiment behind a piece of text?\\nप्राकृतिक भाषा प्रसंस्करण (NLP) का कौन सा कार्य किसी पाठ के पीछे भावनात्मक स्वर या भावना निर्धारित करने से संबंधित है?', 'Named Entity Recognition', 'Part-of-Speech Tagging', 'Sentiment Analysis', 'Machine Translation', 'C', 'Sentiment Analysis (or Opinion Mining) determines the emotional tone of text — positive, negative, or neutral. It is widely used in social media monitoring, customer feedback analysis, and brand reputation management. भावना विश्लेषण पाठ के भावनात्मक स्वर — सकारात्मक, नकारात्मक या तटस्थ — का निर्धारण करता है।', 'easy', 'agent'),
        (42, 'What are the main components of an expert system?\\nविशेषज्ञ प्रणाली के मुख्य घटक क्या हैं?', 'Knowledge Base and Inference Engine only', 'Knowledge Base, Inference Engine, and User Interface', 'Database and Query Processor', 'CPU and Memory', 'B', 'The three main components of an expert system are: (1) Knowledge Base — stores domain-specific facts and rules, (2) Inference Engine — applies logical rules to the knowledge base to derive conclusions, and (3) User Interface — enables communication between user and system. विशेषज्ञ प्रणाली के तीन मुख्य घटक हैं: नॉलेज बेस, इन्फ्रेंस इंजन, और यूज़र इंटरफेस।', 'medium', 'agent'),
        (42, 'Which algorithm is commonly used in training multi-layer neural networks by propagating the error gradient backward through the network?\\nबहु-परत तंत्रिका नेटवर्क को प्रशिक्षित करने में आमतौर पर किस एल्गोरिदम का उपयोग किया जाता है जो नेटवर्क के माध्यम से त्रुटि ग्रेडिएंट को पीछे की ओर प्रसारित करता है?', 'Genetic Algorithm', 'Backpropagation', 'K-Means Clustering', 'Linear Regression', 'B', 'Backpropagation is the core algorithm for training multi-layer neural networks. It calculates the gradient of the loss function with respect to each weight by applying the chain rule, propagating the error backwards from output to input layers. बैकप्रोपेगेशन बहु-परत तंत्रिका नेटवर्क को प्रशिक्षित करने का मुख्य एल्गोरिदम है, जो त्रुटि को आउटपुट से इनपुट की ओर प्रसारित करता है।', 'hard', 'agent'),
        (17, 'Which vitamin is known as ascorbic acid?\\nएस्कॉर्बिक अम्ल किस विटामिन के नाम से जाना जाता है?', 'Vitamin A / विटामिन A', 'Vitamin C / विटामिन C', 'Vitamin D / विटामिन D', 'Vitamin E / विटामिन E', 'B', 'Vitamin C is chemically known as ascorbic acid. It is a water-soluble vitamin essential for collagen synthesis, wound healing, and immune function. Its deficiency causes scurvy. / विटामिन C को रासायनिक रूप से एस्कॉर्बिक अम्ल कहा जाता है। यह एक जल-विलेय विटामिन है जो कोलेजन संश्लेषण, घाव भरने और प्रतिरक्षा कार्य के लिए आवश्यक है। इसकी कमी से स्कर्वी रोग होता है।', 'easy', 'agent'),
        (17, 'Which of the following blood cells is primarily responsible for immune response?\\nप्रतिरक्षा प्रतिक्रिया के लिए मुख्य रूप से कौन सी रक्त कोशिका उत्तरदायी है?', 'Red Blood Cells (RBC) / लाल रक्त कोशिकाएं', 'Platelets / प्लेटलेट्स', 'White Blood Cells (WBC) / श्वेत रक्त कोशिकाएं', 'Plasma / प्लाज्मा', 'C', 'White Blood Cells (leukocytes) are the primary cells of the immune system that defend the body against infections, foreign invaders, and produce antibodies. RBCs carry oxygen, platelets aid in clotting, and plasma is the liquid component. / श्वेत रक्त कोशिकाएं (ल्यूकोसाइट्स) प्रतिरक्षा प्रणाली की प्रमुख कोशिकाएं हैं जो संक्रमणों, विदेशी आक्रमणकारियों से शरीर की रक्षा करती हैं और एंटीबॉडी का उत्पादन करती हैं।', 'easy', 'agent'),
        (17, 'Deficiency of which vitamin causes rickets in children?\\nबच्चों में रिकेट्स रोग किस विटामिन की कमी से होता है?', 'Vitamin A / विटामिन A', 'Vitamin B12 / विटामिन B12', 'Vitamin C / विटामिन C', 'Vitamin D / विटामिन D', 'D', 'Rickets in children is caused by Vitamin D deficiency. Vitamin D (calciferol) regulates calcium and phosphorus absorption in the body. Its deficiency leads to softening and weakening of bones. In adults, Vitamin D deficiency causes osteomalacia. / बच्चों में रिकेट्स विटामिन D की कमी से होता है। विटामिन D (कैल्सीफेरॉल) शरीर में कैल्शियम और फास्फोरस के अवशोषण को नियंत्रित करता है। इसकी कमी से हड्डियां नरम और कमजोर हो जाती हैं।', 'easy', 'agent'),
        (17, 'Which plant hormone is responsible for fruit ripening?\\nफलों के पकने के लिए कौन सा पादप हार्मोन उत्तरदायी है?', 'Auxin / ऑक्सिन', 'Gibberellin / जिबरेलिन', 'Cytokinin / साइटोकाइनिन', 'Ethylene / एथिलीन', 'D', 'Ethylene (C2H4) is a gaseous plant hormone that promotes fruit ripening, senescence, and abscission. It is widely used commercially to ripen fruits like bananas and mangoes. Auxin promotes cell growth, gibberellin promotes stem elongation, and cytokinin promotes cell division. / एथिलीन (C2H4) एक गैसीय पादप हार्मोन है जो फलों के पकने, जीर्णता और पर्णपात को बढ़ावा देता है। इसका व्यावसायिक रूप से केले और आम जैसे फलों को पकाने में उपयोग किया जाता है।', 'medium', 'agent'),
        (18, 'What is the chemical formula of water?\\nजल का रासायनिक सूत्र क्या है?', 'H2O', 'H2O2', 'CO2', 'NaCl', 'A', 'Water has the chemical formula H2O, consisting of two hydrogen atoms covalently bonded to one oxygen atom. H2O2 is hydrogen peroxide, CO2 is carbon dioxide, and NaCl is sodium chloride (common salt). / जल का रासायनिक सूत्र H2O है, जिसमें दो हाइड्रोजन परमाणु सहसंयोजक रूप से एक ऑक्सीजन परमाणु से जुड़े होते हैं।', 'easy', 'agent'),
        (18, 'On the pH scale, a value of 7 indicates that the solution is:\\npH पैमाने पर, मान 7 इंगित करता है कि विलयन है:', 'Acidic / अम्लीय', 'Basic / क्षारीय', 'Neutral / उदासीन', 'Amphoteric / उभयधर्मी', 'C', 'On the pH scale (ranging from 0 to 14), a pH value of 7 indicates a neutral solution — neither acidic nor basic. Values below 7 are acidic (higher H+ concentration), while values above 7 are basic or alkaline. Pure water has a pH of 7 at 25°C. / pH पैमाने (0 से 14) पर, pH मान 7 उदासीन विलयन दर्शाता है — न अम्लीय न क्षारीय। 7 से कम मान अम्लीय और 7 से अधिक मान क्षारीय होते हैं।', 'easy', 'agent'),
        (18, 'Which of the following is NOT a type of chemical reaction?\\nनिम्नलिखित में से कौन एक रासायनिक अभिक्रिया का प्रकार नहीं है?', 'Combination reaction / संयोजन अभिक्रिया', 'Distillation / आसवन', 'Decomposition reaction / वियोजन अभिक्रिया', 'Displacement reaction / विस्थापन अभिक्रिया', 'B', 'Distillation is a physical separation technique based on boiling point differences, not a chemical reaction. The main types of chemical reactions are: combination (A+B→AB), decomposition (AB→A+B), displacement (A+BC→AC+B), double displacement, and redox reactions. / आसवन एक भौतिक पृथक्करण तकनीक है जो क्वथनांक के अंतर पर आधारित है, रासायनिक अभिक्रिया नहीं।', 'medium', 'agent'),
        (18, 'The SI unit of electric current is:\\nविद्युत धारा का SI मात्रक है:', 'Volt / वोल्ट', 'Ampere / एम्पियर', 'Ohm / ओम', 'Watt / वॉट', 'B', 'The SI unit of electric current is Ampere (A), named after Andre-Marie Ampere. One ampere is the flow of one coulomb of charge per second. Volt is the SI unit of potential difference, Ohm is the unit of electrical resistance, and Watt is the unit of power. / विद्युत धारा का SI मात्रक एम्पियर (A) है। वोल्ट विभवांतर का, ओम प्रतिरोध का, और वॉट शक्ति का मात्रक है।', 'easy', 'agent'),
        (21, 'What comes next in the series: 2, 6, 12, 20, 30, ?', '40', '42', '44', '36', 'B', 'The pattern follows n(n+1): 1×2=2, 2×3=6, 3×4=12, 4×5=20, 5×6=30. The next term is 6×7=42. Alternatively, differences between consecutive terms increase by 2: +4, +6, +8, +10, so the next difference is +12, giving 30+12=42.', 'easy', 'agent'),
        (21, 'In a certain code language, RAJASTHAN is written as SBKBTUIBO. How will COMPUTER be written in that same code language?', 'DPNQVUFS', 'DPNQVFST', 'DNQQVUFS', 'DPMQVFST', 'A', "The coding pattern adds 1 to each letter\\'s position: R(18)→S(19), A(1)→B(2), J(10)→K(11), A(1)→B(2), S(19)→T(20), T(20)→U(21), H(8)→I(9), A(1)→B(2), N(14)→O(15). Applying the same to COMPUTER: C→D, O→P, M→N, P→Q, U→V, T→U, E→F, R→S, giving DPNQVUFS.", 'medium', 'agent'),
        (21, 'A is the father of B. B is the sister of C. C is the mother of D. How is A related to D?', 'Father', 'Grandfather', 'Uncle', 'Brother', 'B', 'A is the father of B, and B and C are siblings (sisters), so A is also the father of C. C is the mother of D, therefore A is the maternal grandfather of D. Since "Grandfather" is the closest option from the given choices, B is correct.', 'medium', 'agent'),
        (21, 'Rajesh walks 5 km North, then turns right and walks 3 km, then turns right again and walks 5 km. How far is he from the starting point and in which direction?', '3 km East', '3 km West', '5 km North', '8 km South', 'A', 'Starting from origin O(0,0): 5 km North to A(0,5); then right (East) 3 km to B(3,5); then right (South) 5 km to C(3,0). The final position is (3,0), which is 3 km East of the starting point.', 'medium', 'agent'),
        (21, 'Find the missing term in the series: A, E, I, M, ?', 'P', 'Q', 'R', 'S', 'B', "The pattern adds 4 to each letter\\'s position value: A(1), E(5=1+4), I(9=5+4), M(13=9+4). The next term is M(13)+4 = Q(17). Note: The sequence follows every 4th letter starting from A.", 'easy', 'agent'),
        (22, 'Consider a sequence of arrows showing rotation: ↑ (up), → (right), ↓ (down), ?. Which arrow comes next in the series?', '↑ (up)', '← (left)', '↓ (down)', '↗ (up-right)', 'B', 'The arrow rotates 90° clockwise in each step. Up (↑) → Right (→) → Down (↓) → Left (←). So the next figure is the left-pointing arrow (←).', 'easy', 'agent'),
        (22, 'A square sheet of paper is folded in half vertically and then in half horizontally. A hole is punched through the folded paper at the center of the folded shape. When completely unfolded, how many holes will appear on the paper?', '1', '2', '4', '8', 'C', 'First fold (vertical) creates 2 layers. Second fold (horizontal) doubles the layers to 4. When a hole is punched through all 4 layers and the paper is unfolded, the hole appears in all 4 quadrants symmetrically, giving a total of 4 holes.', 'medium', 'agent'),
        (22, 'Select the figure that will replace the question mark (?) in the following figure matrix:\\nRow 1: Star, Diamond, Circle\\nRow 2: Diamond, Circle, Star\\nRow 3: Circle, Star, ?', 'Star', 'Diamond', 'Circle', 'Triangle', 'B', 'Each row contains the same three shapes (Star, Diamond, Circle) in different cyclic orders. Row 1: Star→Diamond→Circle. Row 2: Diamond→Circle→Star (shifted left by 1). Row 3: Circle→Star→? The missing shape is Diamond, following the cyclic pattern.', 'medium', 'agent'),
        (22, 'How many rectangles are there in a 3×3 grid (3 rows and 3 columns of small squares)?', '9', '18', '36', '24', 'C', 'Number of rectangles in an m×n grid = C(m+1,2) × C(n+1,2). Here, m=3, n=3. Number of ways to choose 2 horizontal lines from 4 = C(4,2) = 6. Number of ways to choose 2 vertical lines from 4 = C(4,2) = 6. Total rectangles = 6 × 6 = 36.', 'hard', 'agent'),
        (22, 'Which option shows the correct mirror image of the number 2026 when a mirror is placed vertically to its right?', '6202', '9202', '2026', '6022', 'A', 'When a mirror is placed vertically on the right, the image undergoes lateral inversion — the entire number is reversed left-to-right. The number 2026 when laterally inverted becomes 6202 (digits read from right to left after mirroring). Note: 0 and 2 and 6 remain recognizable after lateral inversion.', 'easy', 'agent'),
        (23, 'If 25% of a number is 80, what is 60% of the same number?', '180', '192', '200', '160', 'B', 'Let the number be x. 25% of x = 80 → x × 25/100 = 80 → x = 80 × 100/25 = 320. Now, 60% of 320 = 320 × 60/100 = 192. Alternate: 25% = 1/4, so x = 4×80 = 320; 60% = 3/5, so 3/5 × 320 = 192.', 'easy', 'agent'),
        (23, 'A shopkeeper buys an item for Rs. 500 and sells it at a profit of 15%. What is the selling price?', 'Rs. 525', 'Rs. 550', 'Rs. 565', 'Rs. 575', 'D', 'Profit = 15% of Cost Price (CP). Profit = 500 × 15/100 = Rs. 75. Selling Price (SP) = CP + Profit = 500 + 75 = Rs. 575. Alternate formula: SP = CP × (100 + Profit%)/100 = 500 × 115/100 = 575.', 'easy', 'agent'),
        (23, 'The average of 5 numbers is 24. If one number is removed, the average of the remaining 4 numbers becomes 22. What is the number that was removed?', '28', '30', '32', '26', 'C', 'Sum of 5 numbers = 5 × 24 = 120. Sum of remaining 4 numbers = 4 × 22 = 88. Removed number = 120 - 88 = 32. Formula: Removed number = (Initial sum) - (New sum) = (n1 × avg1) - (n2 × avg2).', 'medium', 'agent'),
        (23, 'Find the Simple Interest on Rs. 4000 at 8% per annum for 3 years.', 'Rs. 840', 'Rs. 920', 'Rs. 960', 'Rs. 880', 'C', 'Simple Interest (SI) = (P × R × T) / 100, where P = Principal (4000), R = Rate (8%), T = Time (3 years). SI = (4000 × 8 × 3) / 100 = 96000/100 = Rs. 960.', 'easy', 'agent'),
        (24, 'A bar graph shows the annual sales (in crores) of a company: 2019: 40, 2020: 45, 2021: 50, 2022: 60, 2023: 55. What is the average annual sales over these 5 years?', '48 crores', '50 crores', '52 crores', '55 crores', 'B', 'Total sales = 40 + 45 + 50 + 60 + 55 = 250 crores. Number of years = 5. Average = Total sum / Number of years = 250 / 5 = 50 crores.', 'easy', 'agent'),
        (24, 'Study the following table showing marks of three students in three subjects:\\nStudent | Math | Science | English\\nA | 85 | 90 | 80\\nB | 75 | 80 | 85\\nC | 90 | 85 | 75\\n\\nWhat is the total marks obtained by student B?', '235', '240', '245', '255', 'B', 'Total marks of Student B = Math (75) + Science (80) + English (85) = 240. Direct addition from the table row for student B.', 'easy', 'agent'),
        (24, 'A pie chart shows the distribution of 3600 students across different streams:\\nScience: 30%, Commerce: 25%, Arts: 20%, Engineering: 15%, Others: 10%\\n\\nHow many students are enrolled in Science?', '900', '1080', '720', '1200', 'B', 'Number of Science students = 30% of 3600 = 3600 × 30/100 = 1080. Formula: Value = (Percentage/100) × Total.', 'easy', 'agent'),
        (24, 'In a company, the ratio of male to female employees is 3 : 2. If the number of male employees is 240, what is the total number of employees?', '360', '400', '380', '420', 'B', 'Let common factor be x. Males = 3x, Females = 2x. Given 3x = 240 → x = 80. Total employees = 3x + 2x = 5x = 5 × 80 = 400.', 'medium', 'agent'),
        (24, 'A bar graph shows the population (in thousands) of a town over 5 years:\\n2018: 50, 2019: 55, 2020: 60, 2021: 66, 2022: 72\\n\\nWhat is the percentage increase in population from 2018 to 2022?', '40%', '42%', '44%', '48%', 'C', 'Increase in population = 72 - 50 = 22 thousand. Percentage increase = (Increase / Original) × 100 = (22/50) × 100 = 44%. Formula: % Change = (New - Old) / Old × 100.', 'medium', 'agent'),
        (14, "Who was the first constitutional Governor of Rajasthan after the state\\'s reorganisation in 1956?\\nराजस्थान के 1956 में पुनर्गठन के बाद प्रथम संवैधानिक राज्यपाल कौन थे?", 'Kalyan Singh', 'Gurumukh Nihal Singh', 'Pratibha Patil', 'Sampurnanand', 'B', 'Gurumukh Nihal Singh served as the first constitutional Governor of Rajasthan from 1 November 1956 to 16 April 1962. Before the reorganisation, Maharaja Man Singh II served as Rajpramukh (ceremonial head) from 30 March 1949.', 'easy', 'agent'),
        (14, 'Where is the principal seat of the Rajasthan High Court?\\nराजस्थान उच्च न्यायालय की मुख्य पीठ कहाँ स्थित है?', 'Jaipur', 'Jodhpur', 'Udaipur', 'Kota', 'B', "The Rajasthan High Court was established on 29 August 1949. After the state\\'s full integration in 1956, the principal seat was shifted to Jodhpur based on the Satyanarayan Rao Committee recommendation. Jaipur has a permanent bench established on 31 January 1977.", 'easy', 'agent'),
        (14, 'Who is the current Speaker of the Rajasthan Legislative Assembly (as of 2025-26)?\\nराजस्थान विधानसभा के वर्तमान अध्यक्ष (2025-26 तक) कौन हैं?', 'Bhajan Lal Sharma', 'Vasudev Devnani', 'Om Birla', 'Diya Kumari', 'B', 'Vasudev Devnani (BJP), representing the Ajmer North constituency, is the Speaker of the 16th Rajasthan Legislative Assembly. He was elected Speaker after the 2023 Assembly elections and continues to hold the position in 2025-26.', 'medium', 'agent'),
        (14, 'What is the total number of seats in the Rajasthan Legislative Assembly?\\nराजस्थान विधान सभा में कुल कितनी सीटें हैं?', '250', '200', '300', '175', 'B', 'The Rajasthan Legislative Assembly (Vidhan Sabha) is unicameral with 200 seats filled by direct election from single-member constituencies. The state also sends 25 members to the Lok Sabha and 10 to the Rajya Sabha.', 'easy', 'agent'),
        (14, 'Who was the first woman Governor of Rajasthan?\\nराजस्थान की प्रथम महिला राज्यपाल कौन थीं?', 'Sarojini Naidu', 'Margaret Alva', 'Pratibha Patil', 'Vasundhara Raje', 'C', 'Pratibha Devisingh Patil served as the 17th Governor of Rajasthan from 8 November 2004 to 23 June 2007. She later became the 12th President of India (2007-2012), the first woman to hold that office.', 'medium', 'agent'),
        (15, 'When and where was the Panchayati Raj system first introduced in India?\\nभारत में पंचायती राज व्यवस्था सबसे पहले कब और कहाँ लागू की गई?', '2 October 1959, Nagaur (Rajasthan)', '2 October 1952, Delhi', '24 April 1993, Jaipur', '15 August 1950, Nagpur', 'A', 'Rajasthan became the first state in India to introduce Panchayati Raj, inaugurated by Prime Minister Jawaharlal Nehru at Nagaur on 2 October 1959. It was based on the recommendations of the Balwant Rai Mehta Committee (1957).', 'easy', 'agent'),
        (15, 'Which Constitutional Amendment gave constitutional status to Panchayati Raj institutions?\\nकिस संवैधानिक संशोधन ने पंचायती राज संस्थाओं को संवैधानिक दर्जा दिया?', '74th Amendment', '73rd Amendment', '42nd Amendment', '44th Amendment', 'B', 'The 73rd Constitutional Amendment Act, 1992 (effective 24 April 1993) added Part IX (Articles 243 to 243-O) and the Eleventh Schedule (29 functional items) to the Constitution, giving constitutional status to Panchayats.', 'easy', 'agent'),
        (15, 'What is the minimum reservation for women in Panchayats under the 73rd Amendment?\\n73वें संशोधन के तहत पंचायतों में महिलाओं के लिए न्यूनतम आरक्षण कितना है?', '50%', '25%', '33⅓% (One-third)', '40%', 'C', 'Article 243D mandates that not less than one-third (33⅓%) of the total seats and chairperson positions in Panchayats shall be reserved for women. This includes reservation within SC/ST quotas as well.', 'medium', 'agent'),
        (15, 'Which is the apex body of the three-tier Panchayati Raj system?\\nत्रि-स्तरीय पंचायती राज व्यवस्था में सर्वोच्च निकाय कौन सा है?', 'Gram Sabha', 'Gram Panchayat', 'Panchayat Samiti', 'Zila Parishad', 'D', 'Zila Parishad is the apex (district-level) body of the three-tier Panchayati Raj system. The hierarchy is: Gram Panchayat (village level) → Panchayat Samiti (block level) → Zila Parishad (district level).', 'easy', 'agent'),
        (15, 'What is the fixed tenure of a Panchayat body under Article 243E?\\nअनुच्छेद 243E के तहत पंचायत का निश्चित कार्यकाल कितना है?', '3 years', '4 years', '5 years', '6 years', 'C', 'Article 243E provides a fixed five-year term for Panchayats from its first meeting. If dissolved earlier, fresh elections must be held within six months of dissolution.', 'medium', 'agent'),
        (16, 'Who presented the Rajasthan Budget 2025-26?\\nराजस्थान बजट 2025-26 किसने प्रस्तुत किया?', 'Bhajan Lal Sharma', 'Diya Kumari', 'Vasudev Devnani', 'Kalraj Mishra', 'B', 'Deputy Chief Minister and Finance Minister Diya Kumari presented the Rajasthan Budget 2025-26 on 19 February 2025 in the Legislative Assembly as her second full budget.', 'easy', 'agent'),
        (16, 'What was the total expenditure outlay of the Rajasthan Budget 2025-26?\\nराजस्थान बजट 2025-26 का कुल व्यय प्रावधान कितना था?', '₹3.79 lakh crore', '₹5.37 lakh crore', '₹6.10 lakh crore', '₹4.50 lakh crore', 'B', 'The total expenditure (including debt repayment) of the Rajasthan Budget 2025-26 was approximately ₹5.37 lakh crore, with a projected GSDP of ₹19.89 lakh crore.', 'medium', 'agent'),
        (16, 'What made the Rajasthan Budget 2025-26 unique?\\nराजस्थान बजट 2025-26 को किस बात ने अद्वितीय बनाया?', 'It was a Zero-Based Budget', 'It was the first Green Budget', 'It was a fully Digital Budget', 'It was a Women-Centric Budget', 'B', 'Rajasthan\\\'s first-ever "Green Budget" allocated ₹27,854 crore (11.34% of scheme expenditure) to climate action, renewable energy, sustainable agriculture, and environmental conservation initiatives.', 'medium', 'agent'),
        (16, 'What was the allocation for the Mukhyamantri Ayushman Arogya (MAA) Yojana in Budget 2025-26?\\nबजट 2025-26 में मुख्यमंत्री आयुष्मान आरोग्य (MAA) योजना के लिए कितना आवंटन किया गया?', '₹1,500 crore', '₹2,500 crore', '₹3,500 crore', '₹5,000 crore', 'C', 'The MAA Fund received ₹3,500 crore in the 2025-26 Budget for free diagnostic tests and medicines. The scheme also introduced interstate portability for healthcare access across India.', 'hard', 'agent'),
        (16, 'How many free electricity units per month are provided under the CM Free Electricity Scheme in Rajasthan Budget 2025-26?\\nराजस्थान बजट 2025-26 में मुख्यमंत्री मुफ्त बिजली योजना के तहत प्रति माह कितनी मुफ्त बिजली इकाइयाँ दी जाती हैं?', '100 units', '150 units', '200 units', '50 units', 'B', 'The free electricity limit was increased from 100 to 150 units per month under the CM Free Electricity Scheme. Additionally, 50,000 new agricultural and 5 lakh new domestic power connections were announced.', 'medium', 'agent'),
        (19, 'Which Rajasthan Royals player won the Orange Cap in IPL 2026?\\nIPL 2026 में ऑरेंज कैप किस राजस्थान रॉयल्स खिलाड़ी ने जीता?', 'Sanju Samson', 'Virat Kohli', 'Vaibhav Sooryavanshi', 'Shubman Gill', 'C', 'Vaibhav Sooryavanshi scored 776 runs in IPL 2026 at a strike rate of 237.30 to win the Orange Cap. He also won MVP, Emerging Player, Super Striker, and Super Sixes awards in a record-breaking season.', 'medium', 'agent'),
        (19, 'Who is the current Governor of Rajasthan (as of 2025-26)?\\nराजस्थान के वर्तमान राज्यपाल (2025-26 तक) कौन हैं?', 'Kalraj Mishra', 'Kalyan Singh', 'Haribhau Kisanrao Bagade', 'Margaret Alva', 'C', 'Haribhau Kisanrao Bagade assumed office as the 22nd Governor of Rajasthan on 31 July 2024. He succeeded Kalraj Mishra who served from 9 September 2019 to 30 July 2024.', 'easy', 'agent'),
        (19, 'Which Rajasthan folk artist, a master of the bhapang instrument, was awarded the Padma Shri in 2026?\\nभपंग वादन में निपुण किस राजस्थानी लोक कलाकार को 2026 में पद्म श्री से सम्मानित किया गया?', 'Taga Ram Bheel', 'Gafruddin Mewati Jogi', 'Baijnath Maharaj', 'Swami Brahmadev Ji', 'B', 'Gafruddin Mewati Jogi, a master of the traditional bhapang instrument from the Mewat region, was conferred the Padma Shri in 2026. He has performed for Queen Elizabeth II and has mastered over 2,500 Mahabharata couplets.', 'medium', 'agent'),
        (19, "Which team won the Senior Men\\'s Gold Medal at the 5th Soft Hockey National Championship 2025-26 held in Jaipur?\\nजयपुर में आयोजित 5वीं सॉफ्ट हॉकी राष्ट्रीय चैंपियनशिप 2025-26 में सीनियर पुरुषों का स्वर्ण पदक किस टीम ने जीता?", 'Puducherry', 'Rajasthan', 'Maharashtra', 'Punjab', 'B', "Rajasthan defeated Maharashtra 5-3 to win the Senior Men\\'s gold medal. Rajasthan also won gold in Junior Boys, Junior Girls, Sub-Junior Boys, and Sub-Junior Girls categories.", 'hard', 'agent'),
        (19, "Where was the Congress party\\'s organisational training camp held in Rajasthan in June 2026?\\nजून 2026 में राजस्थान में कांग्रेस पार्टी का संगठनात्मक प्रशिक्षण शिविर कहाँ आयोजित हुआ?", 'Jaipur', 'Jodhpur', 'Pushkar', 'Udaipur', 'C', 'The Congress party held a 10-day training camp in Pushkar (Ajmer district) from June 1-2, 2026, with 50 district presidents from Rajasthan. Rahul Gandhi attended the concluding session.', 'hard', 'agent'),
        (20, 'Which team won the IPL 2026 title?\\nIPL 2026 का खिताब किस टीम ने जीता?', 'Rajasthan Royals', 'Gujarat Titans', 'Royal Challengers Bengaluru', 'Mumbai Indians', 'C', 'Royal Challengers Bengaluru (RCB) defeated Gujarat Titans by 5 wickets in the final on 31 May 2026 at Narendra Modi Stadium, Ahmedabad, winning their second consecutive IPL title. Virat Kohli was Player of the Match.', 'easy', 'agent'),
        (20, 'Who is the current Chairman of ISRO (as of 2026)?\\nISRO के वर्तमान अध्यक्ष (2026 तक) कौन हैं?', 'Dr. S. Somnath', 'Dr. V. Narayanan', 'Dr. K. Sivan', 'Dr. P. Veeramuthuvel', 'B', 'Dr. V. Narayanan assumed charge as Chairman of ISRO and Secretary, Department of Space on 14 January 2025 for a two-year term, succeeding Dr. S. Somnath. He is a rocket propulsion expert.', 'medium', 'agent'),
        (20, 'Which joint ISRO-NASA satellite was launched on 30 July 2025?\\n30 जुलाई 2025 को ISRO-NASA का कौन सा संयुक्त उपग्रह प्रक्षेपित किया गया?', 'GSAT-7R', 'Oceansat-3A', 'NISAR', 'Cartosat-3', 'C', 'NISAR (NASA-ISRO Synthetic Aperture Radar) is the first joint Earth observation satellite between ISRO and NASA. Launched aboard GSLV-F16 from Sriharikota, it carries dual-frequency L-band and S-band SAR.', 'medium', 'agent'),
        (20, 'Who is the 53rd Chief Justice of India (as of 2026)?\\nभारत के 53वें मुख्य न्यायाधीश (2026 तक) कौन हैं?', 'Justice D.Y. Chandrachud', 'Justice B.V. Nagarathna', 'Justice Surya Kant', 'Justice N.V. Ramana', 'C', 'Justice Surya Kant assumed office as the 53rd Chief Justice of India on 24 November 2025. Justice B.V. Nagarathna is expected to become the first woman CJI in September 2027.', 'medium', 'agent'),
        (20, "What is the name of ISRO\\'s first uncrewed Gaganyaan test flight expected to launch in 2026?\\n2026 में प्रक्षेपित होने वाली ISRO की पहली मानवरहित गगनयान परीक्षण उड़ान का नाम क्या है?", 'G-1', 'H-1', 'LVM3', 'Vyommitra', 'A', 'G-1 is the first uncrewed test flight of the Gaganyaan programme, expected to launch in August-September 2026. It will carry Vyommitra, a female-looking half-humanoid robot, to test life-support and re-entry systems.', 'hard', 'agent'),
        (25, 'Microprocessors based on VLSI (Very Large Scale Integration) technology were introduced in which generation of computers?\\nवीएलएसआई (वेरी लार्ज स्केल इंटीग्रेशन) तकनीक पर आधारित माइक्रोप्रोसेसर कंप्यूटर की किस पीढ़ी में शुरू किए गए थे?', 'Second Generation / द्वितीय पीढ़ी', 'Third Generation / तृतीय पीढ़ी', 'Fourth Generation / चतुर्थ पीढ़ी', 'Fifth Generation / पंचम पीढ़ी', 'C', 'Fourth generation computers (1971–1990) used VLSI technology, which enabled the development of microprocessors on a single chip. The Intel 4004 (1971) was the first microprocessor. Second generation used transistors, third used SSI/MSI ICs, and fifth generation focuses on AI and ULSI technology.\\nचतुर्थ पीढ़ी के कंप्यूटरों (1971-1990) में वीएलएसआई तकनीक का उपयोग किया गया, जिसने एक चिप पर माइक्रोप्रोसेसर के विकास को संभव बनाया। इंटेल 4004 (1971) पहला माइक्रोप्रोसेसर था। द्वितीय पीढ़ी में ट्रांजिस्टर, तृतीय पीढ़ी में एसएसआई/एमएसआई आईसी का उपयोग हुआ, और पंचम पीढ़ी एआई और यूएलएसआई तकनीक पर केंद्रित है।', 'medium', 'agent'),
        (25, 'Which of the following devices functions as BOTH an input device and an output device?\\nनिम्नलिखित में से कौन सा उपकरण इनपुट और आउटपुट दोनों उपकरणों के रूप में कार्य करता है?', 'Keyboard / कीबोर्ड', 'Monitor / मॉनिटर', 'Touch Screen / टच स्क्रीन', 'Printer / प्रिंटर', 'C', 'A touch screen functions as both input and output: it displays information (output) and detects touch as input. A keyboard is only an input device, a monitor is only an output device, and a printer is only an output device.\\nटच स्क्रीन इनपुट और आउटपुट दोनों के रूप में कार्य करती है: यह सूचना प्रदर्शित करती है (आउटपुट) और स्पर्श को इनपुट के रूप में पहचानती है। कीबोर्ड केवल इनपुट, मॉनिटर केवल आउटपुट और प्रिंटर केवल आउटपुट डिवाइस है।', 'easy', 'agent'),
        (25, 'A computer system has 64 MB of RAM. If each memory address stores 1 byte, how many address lines are minimally required to address this entire memory?\\nएक कंप्यूटर सिस्टम में 64 MB RAM है। यदि प्रत्येक मेमोरी पता 1 बाइट संग्रहीत करता है, तो इस पूरी मेमोरी को एड्रेस करने के लिए न्यूनतम कितनी एड्रेस लाइनों की आवश्यकता है?', '24', '26', '32', '20', 'B', '64 MB = 64 x 1024 x 1024 = 2^6 x 2^10 x 2^10 = 2^26 bytes. Since each address stores 1 byte and 2^n addresses require n address lines, 26 address lines are needed to address 2^26 locations.\\n64 MB = 64 x 1024 x 1024 = 2^6 x 2^10 x 2^10 = 2^26 बाइट। चूंकि प्रत्येक पता 1 बाइट संग्रहीत करता है और 2^n पतों के लिए n एड्रेस लाइनों की आवश्यकता होती है, 2^26 स्थानों को एड्रेस करने के लिए 26 एड्रेस लाइनों की आवश्यकता है।', 'hard', 'agent'),
        (25, 'A device driver belongs to which category of software?\\nडिवाइस ड्राइवर सॉफ्टवेयर की किस श्रेणी में आता है?', 'Application Software / एप्लीकेशन सॉफ्टवेयर', 'Utility Software / यूटिलिटी सॉफ्टवेयर', 'System Software / सिस्टम सॉफ्टवेयर', 'Programming Software / प्रोग्रामिंग सॉफ्टवेयर', 'C', 'A device driver is system software that provides an interface between the operating system and hardware devices. It manages communication between hardware and the OS kernel, making it an essential component of system software, not application or utility software.\\nडिवाइस ड्राइवर सिस्टम सॉफ्टवेयर है जो ऑपरेटिंग सिस्टम और हार्डवेयर उपकरणों के बीच इंटरफेस प्रदान करता है। यह हार्डवेयर और OS कर्नेल के बीच संचार का प्रबंधन करता है, इसे एप्लीकेशन या यूटिलिटी सॉफ्टवेयर नहीं बल्कि सिस्टम सॉफ्टवेयर का आवश्यक घटक बनाता है।', 'medium', 'agent'),
        (25, 'Which type of memory is non-volatile, read-only, and used to store the firmware (BIOS) of a computer?\\nकिस प्रकार की मेमोरी नॉन-वोलाटाइल, रीड-ओनली होती है और कंप्यूटर के फर्मवेयर (BIOS) को संग्रहीत करने के लिए उपयोग की जाती है?', 'RAM / रैम', 'Cache Memory / कैश मेमोरी', 'ROM / रॉम', 'SSD / एसएसडी', 'C', 'ROM (Read Only Memory) is non-volatile, meaning it retains data even when power is off. It is pre-programmed during manufacturing with essential firmware such as BIOS/UEFI, which boots the computer. RAM is volatile, cache is high-speed volatile memory, and SSD is secondary storage.\\nROM (रीड ओनली मेमोरी) नॉन-वोलाटाइल है, जिसका अर्थ है कि बिजली बंद होने पर भी यह डेटा बनाए रखती है। यह निर्माण के दौरान BIOS/UEFI जैसे आवश्यक फर्मवेयर के साथ प्री-प्रोग्राम्ड होती है जो कंप्यूटर को बूट करता है। RAM वोलाटाइल, कैश उच्च-गति वोलाटाइल मेमोरी और SSD सेकेंडरी स्टोरेज है।', 'easy', 'agent'),
        (26, 'The binary number 110110 is equivalent to which decimal number?\\nबाइनरी संख्या 110110 किस दशमलव संख्या के बराबर है?', '52', '54', '56', '50', 'B', '110110_2 = 1x2^5 + 1x2^4 + 0x2^3 + 1x2^2 + 1x2^1 + 0x2^0 = 32 + 16 + 0 + 4 + 2 + 0 = 54.\\n110110_2 = 1x2^5 + 1x2^4 + 0x2^3 + 1x2^2 + 1x2^1 + 0x2^0 = 32 + 16 + 0 + 4 + 2 + 0 = 54.', 'easy', 'agent'),
        (26, 'The octal number 637 is equivalent to which hexadecimal number?\\nअष्टाधारी संख्या 637 किस षोडश आधारी संख्या के बराबर है?', '19F', '1A7', '1AF', '19E', 'A', 'Convert 637_8 to binary: 6=110, 3=011, 7=111 => 110011111_2. Group into 4-bit nibbles from right: 0001 1001 1111 = 1 9 F => 19F_16.\\n637_8 को बाइनरी में बदलें: 6=110, 3=011, 7=111 => 110011111_2। दाएं से 4-बिट निबल्स में समूहित करें: 0001 1001 1111 = 1 9 F => 19F_16।', 'medium', 'agent'),
        (26, "What is the 1\\'s complement of the binary number 101101?\\nबाइनरी संख्या 101101 का 1\\'s कॉम्प्लीमेंट क्या है?", '010010', '010011', '101110', '100100', 'A', "1\\'s complement is obtained by inverting each bit: 0 becomes 1 and 1 becomes 0. For 101101, inverting gives 010010.\\n1\\'s कॉम्प्लीमेंट प्रत्येक बिट को उलटाकर प्राप्त किया जाता है: 0, 1 हो जाता है और 1, 0 हो जाता है। 101101 के लिए, उलटाने पर 010010 प्राप्त होता है।", 'medium', 'agent'),
        (26, 'What is the result of adding the binary numbers 10111 and 01101?\\nबाइनरी संख्याओं 10111 और 01101 को जोड़ने पर क्या परिणाम प्राप्त होता है?', '100100', '100011', '100010', '101010', 'A', 'Binary addition: 10111 + 01101. Stepwise from LSB: 1+1=0 carry 1; 1+0+carry1=0 carry 1; 1+1+carry1=1 carry 1; 0+1+carry1=0 carry 1; 1+1+carry1=1 carry 1; final carry=1. Result: 100100.\\nबाइनरी जोड़: 10111 + 01101। LSB से चरणबद्ध: 1+1=0 कैरी 1; 1+0+कैरी1=0 कैरी 1; 1+1+कैरी1=1 कैरी 1; 0+1+कैरी1=0 कैरी 1; 1+1+कैरी1=1 कैरी 1; अंतिम कैरी=1। परिणाम: 100100।', 'hard', 'agent'),
        (26, 'The hexadecimal number 2F is equivalent to which decimal number?\\nषोडश आधारी संख्या 2F किस दशमलव संख्या के बराबर है?', '45', '47', '49', '43', 'B', '2F_16 = 2 x 16^1 + F x 16^0 = 2 x 16 + 15 x 1 = 32 + 15 = 47. In hexadecimal, F represents the decimal value 15.\\n2F_16 = 2 x 16^1 + F x 16^0 = 2 x 16 + 15 x 1 = 32 + 15 = 47। षोडश आधारी में, F दशमलव मान 15 को दर्शाता है।', 'easy', 'agent'),
        (27, 'In MS Word, which shortcut key is used to apply justified alignment to a paragraph?\\nMS Word में, पैराग्राफ पर जस्टिफाइड अलाइनमेंट लागू करने के लिए किस शॉर्टकट कुंजी का उपयोग किया जाता है?', 'Ctrl + J', 'Ctrl + E', 'Ctrl + L', 'Ctrl + R', 'A', 'Ctrl+J applies justified alignment, spacing text evenly between both left and right margins. Ctrl+E centers, Ctrl+L left-aligns, and Ctrl+R right-aligns text.\\nCtrl+J जस्टिफाइड अलाइनमेंट लागू करता है, जो टेक्स्ट को बाएं और दाएं दोनों मार्जिन के बीच समान रूप से रखता है। Ctrl+E सेंटर, Ctrl+L लेफ्ट-अलाइन और Ctrl+R राइट-अलाइन करता है।', 'easy', 'agent'),
        (27, 'In MS Excel, what does the mixed cell reference $A1 signify?\\nMS Excel में, मिश्रित सेल रेफरेंस $A1 क्या दर्शाता है?', 'Column A is absolute, row 1 is relative / कॉलम A निरपेक्ष, पंक्ति 1 सापेक्ष', 'Both column and row are absolute / कॉलम और पंक्ति दोनों निरपेक्ष', 'Column A is relative, row 1 is absolute / कॉलम A सापेक्ष, पंक्ति 1 निरपेक्ष', 'Both column and row are relative / कॉलम और पंक्ति दोनों सापेक्ष', 'A', 'In $A1, the dollar sign before the column letter makes column A absolute (it will not change when the formula is copied), while row 1 is relative (it will change when copied to different rows). $A$1 would be fully absolute, and A1 fully relative.\\n$A1 में, कॉलम अक्षर से पहले डॉलर चिह्न कॉलम A को निरपेक्ष बनाता है (फॉर्मूला कॉपी करने पर यह नहीं बदलेगा), जबकि पंक्ति 1 सापेक्ष है (अलग-अलग पंक्तियों में कॉपी करने पर यह बदल जाएगा)। $A$1 पूरी तरह निरपेक्ष और A1 पूरी तरह सापेक्ष होगा।', 'medium', 'agent'),
        (27, 'Which MS PowerPoint view displays miniature versions of all slides and is best suited for reordering them?\\nMS PowerPoint का कौन सा व्यू सभी स्लाइड्स के लघु संस्करण प्रदर्शित करता है और उन्हें पुनर्व्यवस्थित करने के लिए सबसे उपयुक्त है?', 'Normal View / नॉर्मल व्यू', 'Outline View / आउटलाइन व्यू', 'Slide Sorter View / स्लाइड सॉर्टर व्यू', 'Slide Show View / स्लाइड शो व्यू', 'C', 'Slide Sorter View displays thumbnail-sized versions of all slides, allowing the user to easily drag and drop slides to reorder them, add sections, or apply transitions to multiple slides at once.\\nस्लाइड सॉर्टर व्यू सभी स्लाइड्स के थंबनेल-आकार के संस्करण प्रदर्शित करता है, जो उपयोगकर्ता को स्लाइड्स को पुनर्व्यवस्थित करने, सेक्शन जोड़ने या एक साथ कई स्लाइड्स पर ट्रांज़िशन लागू करने की सुविधा देता है।', 'easy', 'agent'),
        (27, 'In MS Access, which type of query allows modification of data through update, delete, or append operations?\\nMS Access में, किस प्रकार की क्वेरी अपडेट, डिलीट या एपेंड ऑपरेशन के माध्यम से डेटा में संशोधन की अनुमति देती है?', 'Select Query / सेलेक्ट क्वेरी', 'Parameter Query / पैरामीटर क्वेरी', 'Action Query / एक्शन क्वेरी', 'Cross-tab Query / क्रॉस-टैब क्वेरी', 'C', 'Action Queries (Update, Delete, Append, Make-Table) modify data in the database. Select queries only retrieve and display data without modification. Parameter queries prompt for input, and Cross-tab queries summarize data in a spreadsheet-like format.\\nएक्शन क्वेरी (अपडेट, डिलीट, एपेंड, मेक-टेबल) डेटाबेस में डेटा को संशोधित करती हैं। सेलेक्ट क्वेरी केवल बिना संशोधन के डेटा प्राप्त कर प्रदर्शित करती हैं। पैरामीटर क्वेरी इनपुट के लिए संकेत देती हैं, और क्रॉस-टैब क्वेरी स्प्रेडशीट-जैसे प्रारूप में डेटा का सारांश प्रस्तुत करती हैं।', 'medium', 'agent'),
        (27, 'What is the default file extension for a macro-enabled workbook in MS Excel 2019?\\nMS Excel 2019 में मैक्रो-सक्षम वर्कबुक के लिए डिफ़ॉल्ट फ़ाइल एक्सटेंशन क्या है?', '.xlsx', '.xlsm', '.xlsb', '.xltx', 'B', '.xlsm is the Excel Macro-Enabled Workbook format that supports VBA macro code. .xlsx is the standard workbook without macro support, .xlsb is the binary workbook format, and .xltx is the Excel template format.\\n.xlsm एक्सेल मैक्रो-सक्षम वर्कबुक प्रारूप है जो VBA मैक्रो कोड का समर्थन करता है। .xlsx मैक्रो समर्थन के बिना मानक वर्कबुक, .xlsb बाइनरी वर्कबुक प्रारूप और .xltx एक्सेल टेम्पलेट प्रारूप है।', 'hard', 'agent'),
        (28, 'In C language, what is the output of the following code? printf("%lu", sizeof(\\\'A\\\'));\\nC भाषा में, निम्नलिखित कोड का आउटपुट क्या है? printf("%lu", sizeof(\\\'A\\\'));', '1', '2', '4', 'Compilation Error / संकलन त्रुटि', 'C', "In C, character constants like \\'A\\' are of type int, not char. Therefore sizeof(\\'A\\') returns sizeof(int), which is typically 4 bytes on most systems. In C++, character constants are of type char, so sizeof(\\'A\\') would return 1 there.\\nC में, \\'A\\' जैसे कैरेक्टर कॉन्सटेंट int प्रकार के होते हैं, char नहीं। इसलिए sizeof(\\'A\\') sizeof(int) लौटाता है, जो अधिकांश सिस्टम पर 4 बाइट होता है। C++ में, कैरेक्टर कॉन्सटेंट char प्रकार के होते हैं, इसलिए वहां sizeof(\\'A\\') 1 लौटाएगा।", 'hard', 'agent'),
        (28, 'Which header file must be included in C to use the malloc() and calloc() functions for dynamic memory allocation?\\nडायनेमिक मेमोरी आवंटन के लिए malloc() और calloc() फंक्शन का उपयोग करने हेतु C में कौन सी हेडर फ़ाइल शामिल की जानी चाहिए?', 'stdio.h', 'stdlib.h', 'string.h', 'conio.h', 'B', 'The malloc(), calloc(), realloc(), and free() functions are declared in the <stdlib.h> (Standard Library) header. stdio.h provides input/output functions, string.h provides string manipulation functions, and conio.h provides console I/O (non-standard, mostly in DOS/Windows compilers).\\nmalloc(), calloc(), realloc() और free() फंक्शन <stdlib.h> (स्टैंडर्ड लाइब्रेरी) हेडर में घोषित किए गए हैं। stdio.h इनपुट/आउटपुट, string.h स्ट्रिंग मैनिपुलेशन और conio.h कंसोल I/O फंक्शन (गैर-मानक, अधिकतर DOS/Windows कंपाइलर में) प्रदान करता है।', 'easy', 'agent'),
        (28, 'What will be the output of the following C code?\\nint a[] = {1, 2, 3, 4, 5}; printf("%d", *(a + 3));\\nनिम्नलिखित C कोड का आउटपुट क्या होगा?\\nint a[] = {1, 2, 3, 4, 5}; printf("%d", *(a + 3));', '3', '4', '5', 'Compilation Error / संकलन त्रुटि', 'B', "In C, the array name \\'a\\' acts as a pointer to the first element. *(a + 3) is equivalent to a[3]. Pointer arithmetic means a+3 moves 3 integer positions (12 bytes if int is 4 bytes) from the base address. a[3] = 4.\\nC में, ऐरे का नाम \\'a\\' पहले तत्व के पॉइंटर के रूप में कार्य करता है। *(a + 3), a[3] के बराबर है। पॉइंटर अंकगणित का अर्थ है कि a+3 बेस एड्रेस से 3 इंटीजर स्थान (यदि int 4 बाइट है तो 12 बाइट) आगे बढ़ता है। a[3] = 4।", 'medium', 'agent'),
        (28, 'Which of the following is the correct syntax to declare a pointer to a function in C that takes an integer argument and returns an integer?\\nएक फंक्शन पॉइंटर घोषित करने का सही सिंटैक्स क्या है जो एक इंटीजर आर्गुमेंट लेता है और इंटीजर लौटाता है?', 'int (*ptr)(int);', 'int *ptr(int);', 'int *(ptr)(int);', 'int (ptr*)(int);', 'A', 'int (*ptr)(int); declares ptr as a pointer to a function that takes an int parameter and returns an int. The parentheses around *ptr are necessary; without them, int *ptr(int); would be interpreted as a function declaration returning an int pointer.\\nint (*ptr)(int); ptr को एक फंक्शन पॉइंटर के रूप में घोषित करता है जो int पैरामीटर लेता है और int लौटाता है। *ptr के चारों ओर कोष्ठक आवश्यक हैं; इनके बिना, int *ptr(int); को int पॉइंटर लौटाने वाले फंक्शन घोषणा के रूप में व्याख्या किया जाएगा।', 'hard', 'agent'),
        (28, 'In C, which storage class specifier makes a local variable retain its value between multiple function calls?\\nC में, कौन सा स्टोरेज क्लास स्पेसिफायर किसी लोकल वेरिएबल को कई फंक्शन कॉल्स के बीच अपना मान बनाए रखने में सक्षम बनाता है?', 'auto', 'register', 'static', 'extern', 'C', "The \\'static\\' storage class specifier when used with a local variable causes it to be initialized only once and retain its value between function invocations. Unlike auto variables, static local variables persist throughout program execution but maintain block scope.\\nलोकल वेरिएबल के साथ उपयोग किया गया \\'static\\' स्टोरेज क्लास स्पेसिफायर इसे केवल एक बार इनिशियलाइज़ करता है और फंक्शन कॉल्स के बीच इसका मान बनाए रखता है। ऑटो वेरिएबल्स के विपरीत, स्टैटिक लोकल वेरिएबल प्रोग्राम निष्पादन के दौरान बने रहते हैं लेकिन ब्लॉक स्कोप बनाए रखते हैं।", 'hard', 'agent'),
        (29, 'In Java, which OOP concept is implemented by declaring instance variables as private and providing public getter and setter methods?\\nJava में, इंस्टेंस वेरिएबल्स को प्राइवेट घोषित करके और पब्लिक गेटर और सेटर मेथड प्रदान करके OOP की किस अवधारणा को कार्यान्वित किया जाता है?', 'Inheritance / इनहेरिटेंस', 'Polymorphism / पॉलीमॉर्फिज्म', 'Encapsulation / एनकैप्सुलेशन', 'Abstraction / एब्स्ट्रैक्शन', 'C', 'Encapsulation is the mechanism of binding data (variables) and methods together as a single unit and restricting direct access to internal data. In Java, making variables private with public getters/setters is the standard way to achieve encapsulation, protecting data integrity.\\nएनकैप्सुलेशन डेटा (वेरिएबल्स) और मेथड्स को एक इकाई के रूप में बांधने और आंतरिक डेटा तक सीधी पहुंच को प्रतिबंधित करने की प्रक्रिया है। Java में, पब्लिक गेटर्स/सेटर्स के साथ वेरिएबल्स को प्राइवेट बनाना एनकैप्सुलेशन प्राप्त करने का मानक तरीका है, जो डेटा अखंडता की रक्षा करता है।', 'easy', 'agent'),
        (29, 'Which of the following correctly describes method overriding in Java?\\nनिम्नलिखित में से कौन Java में मेथड ओवरराइडिंग का सही वर्णन करता है?', 'Same method name with different parameters in the same class / एक ही क्लास में अलग-अलग पैरामीटर के साथ समान मेथड नाम', 'Subclass method with same name, same parameters, and same return type as superclass method / सुपरक्लास मेथड के समान नाम, समान पैरामीटर और समान रिटर्न टाइप वाला सबक्लास मेथड', 'Same method name with different return types in the same class / एक ही क्लास में अलग-अलग रिटर्न टाइप के साथ समान मेथड नाम', 'A class implementing multiple methods with different names / विभिन्न नामों वाले कई मेथड्स को लागू करने वाली क्लास', 'B', 'Method overriding occurs when a subclass defines a method with the exact same name, parameter list, and return type (or covariant return type) as a method in its superclass. This enables runtime polymorphism. Option A describes method overloading.\\nमेथड ओवरराइडिंग तब होती है जब कोई सबक्लास अपने सुपरक्लास के मेथड के समान नाम, पैरामीटर सूची और रिटर्न टाइप (या कोवेरिएंट रिटर्न टाइप) वाला मेथड परिभाषित करता है। यह रनटाइम पॉलीमॉर्फिज्म को सक्षम बनाता है। विकल्प A मेथड ओवरलोडिंग का वर्णन करता है।', 'medium', 'agent'),
        (29, 'How does Java achieve multiple inheritance?\\nJava एकाधिक इनहेरिटेंस को कैसे प्राप्त करता है?', 'Through classes / क्लासेस के माध्यम से', 'Through abstract classes only / केवल एब्स्ट्रैक्ट क्लासेस के माध्यम से', 'Through interfaces only / केवल इंटरफेसेस के माध्यम से', 'Through both abstract classes and interfaces / एब्स्ट्रैक्ट क्लासेस और इंटरफेसेस दोनों के माध्यम से', 'C', 'Java does not support multiple inheritance through classes because of the diamond problem (ambiguity when two parent classes have methods with the same signature). However, a single class can implement multiple interfaces, effectively achieving multiple inheritance of behavior (not state).\\nJava डायमंड प्रॉब्लम (जब दो पैरेंट क्लासेस में समान सिग्नेचर वाले मेथड हों तो अस्पष्टता) के कारण क्लासेस के माध्यम से एकाधिक इनहेरिटेंस का समर्थन नहीं करता है। हालांकि, एक क्लास कई इंटरफेसेस को इम्प्लीमेंट कर सकती है, जो प्रभावी रूप से व्यवहार (स्टेट नहीं) का एकाधिक इनहेरिटेंस प्राप्त करती है।', 'medium', 'agent'),
        (29, 'What will be the output of the following Java code?\\ntry { int x = 10 / 0; System.out.print("A"); } catch (ArithmeticException e) { System.out.print("B"); } finally { System.out.print("C"); }\\nनिम्नलिखित Java कोड का आउटपुट क्या होगा?\\ntry { int x = 10 / 0; System.out.print("A"); } catch (ArithmeticException e) { System.out.print("B"); } finally { System.out.print("C"); }', 'A B C', 'B C', 'A C', 'Compilation Error / संकलन त्रुटि', 'B', '10 / 0 throws ArithmeticException at runtime, so the try block is exited immediately without printing "A". The corresponding catch block executes and prints "B". The finally block always executes regardless of whether an exception occurred, printing "C". Hence the output is "BC".\\n10 / 0 रनटाइम पर ArithmeticException फेंकता है, इसलिए try ब्लॉक से तुरंत बाहर निकल जाता है और "A" प्रिंट नहीं होता है। संबंधित catch ब्लॉक निष्पादित होता है और "B" प्रिंट करता है। finally ब्लॉक हमेशा निष्पादित होता है चाहे कोई अपवाद हुआ हो या नहीं, "C" प्रिंट करता है। इसलिए आउटपुट "BC" है।', 'hard', 'agent'),
        (29, 'In Java, which of the following CANNOT be declared inside a Java interface?\\nJava में, निम्नलिखित में से किसे Java इंटरफेस के अंदर घोषित नहीं किया जा सकता है?', 'A static final variable / एक स्टैटिक फाइनल वेरिएबल', 'A default method (Java 8 onward) / एक डिफ़ॉल्ट मेथड (Java 8 से आगे)', 'A static method (Java 8 onward) / एक स्टैटिक मेथड (Java 8 से आगे)', 'A protected method / एक प्रोटेक्टेड मेथड', 'D', 'In Java, all interface methods are implicitly public. A protected method cannot be declared in an interface. Interfaces can contain: static final variables (constants), abstract methods (implicitly public), default methods (Java 8+), static methods (Java 8+), and private methods (Java 9+).\\nJava में, सभी इंटरफेस मेथड्स इम्प्लिसिटली पब्लिक होते हैं। प्रोटेक्टेड मेथड को इंटरफेस में घोषित नहीं किया जा सकता। इंटरफेस में शामिल हो सकते हैं: स्टैटिक फाइनल वेरिएबल (कॉन्सटेंट), एब्स्ट्रैक्ट मेथड (इम्प्लिसिटली पब्लिक), डिफ़ॉल्ट मेथड (Java 8+), स्टैटिक मेथड (Java 8+), और प्राइवेट मेथड (Java 9+)।', 'hard', 'agent'),
        (30, 'What is the output of the following Python code?\\nprint([x**2 for x in range(5) if x % 2 == 0])\\nनिम्नलिखित Python कोड का आउटपुट क्या है?\\nprint([x**2 for x in range(5) if x % 2 == 0])', '[0, 4, 16]', '[0, 2, 4]', '[1, 9, 16]', '[0, 1, 4, 9, 16]', 'A', 'The list comprehension iterates over range(5) = 0,1,2,3,4. The condition if x%2==0 filters for even numbers: 0,2,4. Squaring each gives 0^2=0, 2^2=4, 4^2=16. So the result is [0, 4, 16].\\nलिस्ट कॉम्प्रिहेंशन range(5) = 0,1,2,3,4 पर पुनरावृति करता है। शर्त if x%2==0 सम संख्याओं के लिए फ़िल्टर करती है: 0,2,4। प्रत्येक का वर्ग करने पर 0^2=0, 2^2=4, 4^2=16 प्राप्त होता है। इसलिए परिणाम [0, 4, 16] है।', 'medium', 'agent'),
        (30, 'Which symbol is used in Python to apply a decorator to a function?\\nPython में किसी फंक्शन पर डेकोरेटर लागू करने के लिए किस चिह्न का उपयोग किया जाता है?', '& (ampersand / एम्परसेंड)', '@ (at sign / एट साइन)', '# (hash / हैश)', '$ (dollar / डॉलर)', 'B', 'The @ symbol is the syntactic sugar for applying decorators in Python. A decorator is placed above a function definition as @decorator_name, which modifies the behavior of the function without permanently changing its source code. Common decorators include @staticmethod, @classmethod, and @property.\\n@ चिह्न Python में डेकोरेटर लागू करने का सिंटैक्टिक शुगर है। डेकोरेटर को @decorator_name के रूप में फंक्शन परिभाषा के ऊपर रखा जाता है, जो स्रोत कोड को स्थायी रूप से बदले बिना फंक्शन के व्यवहार को संशोधित करता है। सामान्य डेकोरेटर में @staticmethod, @classmethod और @property शामिल हैं।', 'easy', 'agent'),
        (30, 'In Python, which file opening mode opens a file for both reading and writing in binary format without truncating it?\\nPython में, कौन सा फ़ाइल ओपनिंग मोड फ़ाइल को छोटा किए बिना बाइनरी प्रारूप में पढ़ने और लिखने दोनों के लिए खोलता है?', 'r+b', 'w+b', 'a+b', 'rb+', 'A', "Mode \\'r+b\\' opens the file for both reading and writing in binary mode. The file pointer starts at the beginning, and the file is NOT truncated (unlike w+b which truncates). Mode a+b appends data at the end. rb+ is not a standard mode (r+b is correct).\\nमोड \\'r+b\\' फ़ाइल को बाइनरी मोड में पढ़ने और लिखने दोनों के लिए खोलता है। फ़ाइल पॉइंटर शुरुआत में होता है, और फ़ाइल को छोटा नहीं किया जाता (w+b के विपरीत जो छोटा करता है)। मोड a+b अंत में डेटा जोड़ता है। rb+ एक मानक मोड नहीं है (r+b सही है)।", 'medium', 'agent'),
        (30, 'What is the output of the following Python code?\\nprint({x: x**2 for x in range(3)})\\nनिम्नलिखित Python कोड का आउटपुट क्या है?\\nprint({x: x**2 for x in range(3)})', '{0: 0, 1: 1, 2: 4}', '{0: 0, 1: 1, 2: 4, 3: 9}', '[0: 0, 1: 1, 2: 4]', '{1: 1, 2: 4, 3: 9}', 'A', 'This is a dictionary comprehension (enclosed in curly braces). It iterates over range(3) i.e., x = 0, 1, 2 and creates key-value pairs where x is the key and x**2 is the value. Result: {0:0, 1:1, 2:4}. Option C uses list notation which would be a syntax error.\\nयह एक डिक्शनरी कॉम्प्रिहेंशन है (कर्ली ब्रेसेस में घिरा)। यह range(3) अर्थात x = 0, 1, 2 पर पुनरावृति करता है और की-वैल्यू जोड़े बनाता है जहां x की और x**2 वैल्यू है। परिणाम: {0:0, 1:1, 2:4}। विकल्प C लिस्ट नोटेशन का उपयोग करता है जो सिंटैक्स त्रुटि होगी।', 'easy', 'agent'),
        (4, "Which princely states were merged to form the Matsya Union, the first stage of Rajasthan unification in March 1948?\nमार्च 1948 में राजस्थान एकीकरण के प्रथम चरण 'मत्स्य संघ' में किन रियासतों को शामिल किया गया?", 'Jaipur, Jodhpur, Bikaner, Jaisalmer', 'Alwar, Bharatpur, Dholpur, Karauli', 'Kota, Bundi, Jhalawar, Tonk', 'Udaipur, Banswara, Dungarpur, Pratapgarh', 'B', 'The Matsya Union (17-18 March 1948) consisted of Alwar, Bharatpur, Dholpur, and Karauli with its capital at Alwar. It was inaugurated by N.V. Gadgil at Bharatpur Fort. Shobha Ram was the Prime Minister and Udai Bhan Singh of Dholpur was the Rajpramukh.', 'medium', 'research'),
        (4, "Greater Rajasthan (Vrihat Rajasthan) was inaugurated on 30 March 1949 by whom, marking the foundation of a unified Rajasthan?\n30 मार्च 1949 को 'वृहत राजस्थान' का उद्घाटन किसके द्वारा किया गया, जो एकीकृत राजस्थान की नींव थी?", 'Jawaharlal Nehru', 'Sardar Vallabhbhai Patel', 'Dr. Rajendra Prasad', 'Lord Mountbatten', 'B', 'Sardar Vallabhbhai Patel inaugurated Greater Rajasthan on 30 March 1949 in Jaipur. This fourth stage merged Jaipur, Jodhpur, Bikaner, and Jaisalmer with the United Rajasthan. Maharana Bhupal Singh became Maha-Rajpramukh, and Hiralal Shastri was appointed Prime Minister. This day is celebrated as Rajasthan Day.', 'medium', 'research'),
        (4, "Who was appointed as the first Chief Minister of Rajasthan after the formation of the United State of Greater Rajasthan in May 1949?\nमई 1949 में 'संयुक्त वृहत राजस्थान' के गठन के बाद राजस्थान के प्रथम मुख्यमंत्री के रूप में किसे नियुक्त किया गया?", 'Mohan Lal Sukhadia', 'Hiralal Shastri', 'Tika Ram Paliwal', 'Jai Narayan Vyas', 'B', 'Hiralal Shastri became the first Chief Minister of Rajasthan on 7 April 1949. The post of Prime Minister was abolished in the fifth stage (15 May 1949) when the CM office was created. Tika Ram Paliwal was the first elected CM (1952); Mohan Lal Sukhadia was CM at the time of the 7th stage (1956).', 'easy', 'research'),
        (5, "Which of the following major forts of Rajasthan is NOT included in the UNESCO World Heritage 'Hill Forts of Rajasthan' (2013) inscription?\nनिम्नलिखित में से कौन सा प्रमुख राजस्थानी किला यूनेस्को विश्व धरोहर 'राजस्थान के पहाड़ी किलों' (2013) में शामिल नहीं है?", 'Chittorgarh Fort', 'Kumbhalgarh Fort', 'Mehrangarh Fort', 'Jaisalmer Fort', 'C', 'The six UNESCO Hill Forts of Rajasthan (2013) are: Chittorgarh, Kumbhalgarh, Ranthambore, Gagron, Amber, and Jaisalmer. Mehrangarh Fort (Jodhpur), built by Rao Jodha in 1459, is not part of the UNESCO list, though it is a major tourist attraction and well-preserved fort.', 'medium', 'research'),
        (6, "The Chari folk dance of Rajasthan, in which women balance a brass pot with a burning lamp on their heads, is primarily associated with which community?\nराजस्थान का 'चरी' लोक नृत्य, जिसमें महिलाएं सिर पर जलते दीपक वाली पीतल की पात्रा को संतुलित करती हैं, मुख्यतः किस समुदाय से जुड़ा है?", 'Bhil', 'Kalbeliya', 'Gujjar', 'Kamad', 'C', 'Chari dance is performed by women of the Gujjar (Gurjar) community in the Kishangarh and Ajmer regions. The brass pot (chari) contains cotton seeds soaked in oil with a lighted lamp. The renowned dancer Falku Bai of Kishangarh is notably associated with this dance form.', 'easy', 'research'),
        (6, "The traditional string instrument 'Rawanhattha' is primarily associated with which community for narrating the epic of Pabuji in Rajasthan?\nपारंपरिक तंतु वाद्य 'रावणहत्था' राजस्थान में पाबूजी के महाकाव्य के वाचन के लिए मुख्यतः किस समुदाय से जुड़ा है?", 'Manganiyar', 'Bhopa', 'Langha', 'Kalbeliya', 'B', 'The Rawanhattha (a bowed string instrument made from a half coconut shell) is used by the Bhopa community to narrate the epic of Pabuji through phad paintings and ballads. The instrument is considered a predecessor of the violin. Manganiyar and Langha communities use the kamayacha and sindhi sarangi respectively.', 'medium', 'research'),
        (9, "According to Koppen's climate classification, which climate type is found in Jaisalmer district?\nकोपेन के जलवायु वर्गीकरण के अनुसार, जैसलमेर जिले में किस प्रकार की जलवायु पाई जाती है?", 'Aw', 'BShw', 'BWhw', 'Cwg', 'C', "Jaisalmer district falls under the BWhw (Hot Desert/Arid) climate type as per Koppen's classification, with average annual rainfall below 20 cm. This is a standard RPSC question testing knowledge of Koppen climate zones in Rajasthan.", 'easy', 'research'),
        (9, "As per Koppen's classification, which region of Rajasthan experiences 'Aw' type of climate?\nकोपेन के वर्गीकरण के अनुसार, राजस्थान के किस क्षेत्र में 'Aw' प्रकार की जलवायु पाई जाती है?", 'Western Rajasthan\nपश्चिमी राजस्थान', 'Northern Rajasthan\nउत्तरी राजस्थान', 'Southern Rajasthan\nदक्षिणी राजस्थान', 'Eastern Rajasthan\nपूर्वी राजस्थान', 'C', "The 'Aw' (Tropical Humid/Savanna) climate type is found in southern Rajasthan covering districts like Banswara, Dungarpur, Jhalawar, Kota and Baran. These areas receive over 80 cm of rainfall annually. This was asked in RPSC Sr. Teacher 2022 exam.", 'medium', 'research'),
        (1, 'Which ancient site in Rajasthan has evidence of the earliest ploughed field?\nराजस्थान के किस प्राचीन स्थल पर सबसे पुराने जुते हुए खेत के प्रमाण मिले?', 'Ahad', 'Kalibanga', 'Bairath', 'Gilund', 'B', 'Kalibanga (Hanumangarh) is an Indus Valley site with evidence of the earliest ploughed field in the world. It is a major Harappan site in Rajasthan.', 'medium', 'research'),
        (1, 'The ancient name of Bairath was:\nबैराठ का प्राचीन नाम था:', 'Madhyamika', 'Viratnagar', 'Tamravati', 'Shrimal', 'B', 'Bairath (Jaipur) was the capital of Matsya Janapada, known in ancient times as Viratnagar. It is associated with the Mahabharata period.', 'medium', 'research'),
        (1, 'Which civilization site is located on the banks of the Ghaggar River in Rajasthan?\nराजस्थान में घग्घर नदी के तट पर कौन सी सभ्यता का स्थल स्थित है?', 'Ahad', 'Kalibanga', 'Balathal', 'Ganeshwar', 'B', 'Kalibanga (Hanumangarh district) is located on the left bank of the Ghaggar (ancient Saraswati) River. It is a pre-Harappan and Harappan site.', 'medium', 'research'),
        (1, 'Which ancient site in Rajasthan is famous for its copper tools and is called the "Copper Age" site?\nराजस्थान का कौन सा प्राचीन स्थल अपने तांबे के औजारों के लिए प्रसिद्ध है और इसे "ताम्र युग" का स्थल कहा जाता है?', 'Kalibanga', 'Ahad', 'Ganeshwar', 'Bairath', 'C', 'Ganeshwar (Sikar) is an important Chalcolithic/Copper Age site. It supplied copper tools to the Harappan civilization and has evidence of copper smelting.', 'medium', 'research'),
        (1, 'The ancient site of Ahad (Ahar) is associated with which archaeological culture?\nप्राचीन स्थल आहड़ (अहार) किस पुरातात्विक संस्कृति से जुड़ा है?', 'Ahar-Banas Culture', 'Malwa Culture', 'Jorwe Culture', 'Ochre Coloured Pottery Culture', 'A', 'Ahad (Udaipur) is the type-site of the Ahar-Banas Chalcolithic Culture (c. 3000-1500 BCE). It is known for white-painted black-and-red ware pottery and is called Tambavati Nagari.', 'hard', 'research'),
        (2, 'Who founded the city of Ajmer?\nअजमेर शहर की स्थापना किसने की?', 'Prithviraj III', 'Arnoraja', 'Ajayaraja Chauhan', 'Vigraharaja IV', 'C', 'Ajayaraja Chauhan founded Ajmer (then called Ajayameru) in the 12th century. He was a ruler of the Shakambhari Chahamana (Chauhan) dynasty.', 'medium', 'research'),
        (2, "Maharana Pratap's horse was named:\nमहाराणा प्रताप के घोड़े का नाम था:", 'Ranveer', 'Chetak', 'Vikram', 'Surya', 'B', "Chetak was Maharana Pratap's loyal horse who died saving him at the Battle of Haldighati (1576). A memorial for Chetak stands at Haldighati.", 'easy', 'research'),
        (2, 'Which Rajput ruler built the Vijay Stambh (Victory Tower) at Chittorgarh?\nचित्तौड़गढ़ में विजय स्तंभ का निर्माण किस राजपूत शासक ने करवाया?', 'Rana Sanga', 'Maharana Pratap', 'Rana Kumbha', 'Rana Udai Singh', 'C', 'Rana Kumbha (r. 1433-1468) built the 9-storey Vijay Stambh (1440-1448 CE) to commemorate his victory over Mahmud Khilji of Malwa. It is dedicated to Lord Vishnu.', 'medium', 'research'),
        (2, 'Who was the founder of the Rathore dynasty in Marwar?\nमारवाड़ में राठौड़ वंश के संस्थापक कौन थे?', 'Rao Jodha', 'Rao Siha', 'Rao Maldeo', 'Rao Bika', 'B', 'Rao Siha (Sihaji) is considered the founder of the Rathore dynasty in Marwar (13th century). Rao Jodha founded the city of Jodhpur in 1459, and Rao Bika founded Bikaner.', 'hard', 'research'),
        (2, 'The Kachhwaha Rajputs established their kingdom at which place near Jaipur?\nकछवाहा राजपूतों ने जयपुर के पास किस स्थान पर अपना राज्य स्थापित किया?', 'Ajmer', 'Amber (Amer)', 'Jodhpur', 'Chittorgarh', 'B', 'The Kachhwaha Rajputs (also called Kachhapaghatas) established their kingdom at Amber in the 11th century. They ruled from Amber Fort until Sawai Jai Singh II founded Jaipur in 1727.', 'medium', 'research'),
        (10, 'Zawar mines in Udaipur are famous for:\nउदयपुर की जावर खानें किसके लिए प्रसिद्ध हैं?', 'Copper', 'Zinc', 'Lead', 'Tungsten', 'B', "Zawar mines (Udaipur) are India's oldest zinc mines, operated by Hindustan Zinc Limited. They are among the world's oldest zinc mining sites dating back to ancient times.", 'easy', 'research'),
        (10, 'Tungsten in Rajasthan is primarily mined at:\nराजस्थान में टंगस्टन का खनन मुख्यतः कहाँ होता है?', 'Khetri', 'Zawar', 'Degana', 'Makrana', 'C', "Degana (Nagaur) produces over 90% of India's tungsten. It is a strategic mineral used in making high-speed steel and electric bulb filaments.", 'easy', 'research'),
        (10, 'Makrana in Rajasthan is world-famous for which mineral?\nराजस्थान का मकराना किस खनिज के लिए विश्व-प्रसिद्ध है?', 'Granite', 'Marble', 'Sandstone', 'Limestone', 'B', "Makrana (Nagaur) marble is world-famous and was used in the construction of the Taj Mahal, Victoria Memorial, and Birla Temple. It is India's finest quality white marble.", 'easy', 'research'),
        (10, 'Khetri mines in Rajasthan are famous for which mineral?\nराजस्थान की खेतड़ी खानें किस खनिज के लिए प्रसिद्ध हैं?', 'Zinc', 'Copper', 'Lead', 'Iron', 'B', 'Khetri (Jhunjhunu district) is the largest copper-producing region in Rajasthan. Khetri Nagar and nearby areas have significant copper deposits mined by Hindustan Copper Limited.', 'medium', 'research'),
        (10, 'Gypsum reserves in Rajasthan are primarily found in which district?\nराजस्थान में जिप्सम के भंडार मुख्यतः किस जिले में पाए जाते हैं?', 'Jodhpur', 'Bikaner', 'Nagaur', 'Barmer', 'C', "Rajasthan produces about 99% of India's gypsum, with the largest reserves in Nagaur district. Gypsum is used in making cement, plaster of Paris, and as a soil conditioner.", 'medium', 'research'),
        (11, 'Indira Gandhi Canal originates from:\nइंदिरा गांधी नहर का उद्गम स्थल है:', 'Sutlej River', 'Harike Barrage', 'Bhakra Dam', 'Ravi River', 'B', 'IGNP originates from Harike Barrage (Punjab) at the confluence of Sutlej and Beas rivers. It is called Maru Ganga / Lifeline of Rajasthan, irrigating vast tracts of the Thar Desert.', 'easy', 'research'),
        (11, 'Which crop is known as the "King of Cereals" and is the most widely grown crop in Rajasthan?\nकिस फसल को "अनाजों का राजा" कहा जाता है और यह राजस्थान में सबसे अधिक उगाई जाने वाली फसल है?', 'Wheat', 'Rice', 'Bajra (Pearl Millet)', 'Maize', 'C', "Bajra (Pearl Millet) is Rajasthan's most important crop, grown across 45% of the state's cultivated area in the kharif season. Rajasthan is India's largest bajra producer.", 'easy', 'research'),
        (11, 'Chambal Valley Project is a joint venture of Rajasthan and which other state?\nचम्बल घाटी परियोजना राजस्थान और किस अन्य राज्य का संयुक्त उपक्रम है?', 'Punjab', 'Gujarat', 'Madhya Pradesh', 'Uttar Pradesh', 'C', 'The Chambal Valley Project is a joint venture between Rajasthan and Madhya Pradesh. It includes Gandhi Sagar Dam, Rana Pratap Sagar Dam, Jawahar Sagar Dam, and Kota Barrage.', 'medium', 'research'),
        (11, 'Mahi Bajaj Sagar Project is located on which river?\nमाही बजाज सागर परियोजना किस नदी पर स्थित है?', 'Chambal', 'Mahi', 'Banas', 'Luni', 'B', 'Mahi Bajaj Sagar Project was built on the Mahi River in Banswara district. It is a joint project of Rajasthan and Gujarat for irrigation and hydroelectric power generation.', 'medium', 'research'),
        (11, 'Which district of Rajasthan is the largest producer of mustard?\nराजस्थान का कौन सा जिला सरसों का सबसे बड़ा उत्पादक है?', 'Jaipur', 'Bikaner', 'Alwar', 'Bharatpur', 'C', "Alwar is the largest mustard-producing district in Rajasthan. Rajasthan as a whole contributes about 40-45% of India's total mustard production, making it the top mustard-producing state.", 'hard', 'research')
    ]
    for q in qs:
        try: c.execute('INSERT INTO questions (topic_id, question_text, option_a, option_b, option_c, option_d, correct_option, explanation, difficulty, source) VALUES (?,?,?,?,?,?,?,?,?,?)', q)
        except: pass

    # Initialize topic mastery
    for t in topics:
        c.execute('INSERT OR IGNORE INTO topic_mastery (topic_id, status) VALUES (?,?)', (t[0], 'not_started'))

    db.commit()
    db.close()


@app.route('/')
def index():
    """Main Dashboard"""
    db = get_db()
    # Overall stats
    tests = db.execute('SELECT COUNT(*) as total, AVG(score) as avg_score, SUM(time_taken_sec) as total_time FROM mock_tests WHERE status="completed"').fetchone()
    last_test = db.execute('SELECT * FROM mock_tests WHERE status="completed" ORDER BY completed_at DESC LIMIT 1').fetchone()

    # Topic mastery summary
    topics = db.execute('''
        SELECT tm.*, t.name, t.subject, t.paper, t.weightage
        FROM topic_mastery tm JOIN topics t ON tm.topic_id = t.id
        ORDER BY tm.current_score ASC NULLS FIRST
    ''').fetchall()

    weak_topics = [t for t in topics if (t['current_score'] or 0) < 60 and t['test_count'] > 0]
    strong_topics = [t for t in topics if (t['current_score'] or 0) >= 70]
    untested = [t for t in topics if t['test_count'] == 0]

    # Recent errors
    recent_errors = db.execute('''
        SELECT el.*, t.name as topic_name, q.question_text
        FROM error_log el JOIN topics t ON el.topic_id = t.id
        JOIN questions q ON el.question_id = q.id
        WHERE el.resolved = 0 ORDER BY el.created_at DESC LIMIT 10
    ''').fetchall()

    # Weekly progress
    week_ago = (datetime.now() - timedelta(days=7)).strftime('%Y-%m-%d')
    weekly_tests = db.execute('SELECT date(completed_at) as d, AVG(score) as avg FROM mock_tests WHERE status="completed" AND completed_at >= ? GROUP BY d ORDER BY d', (week_ago,)).fetchall()

    # Accuracy by error type
    error_dist = db.execute('SELECT error_type, COUNT(*) as cnt FROM error_log GROUP BY error_type ORDER BY cnt DESC').fetchall()

    # Paper-wise performance
    paper_perf = db.execute('SELECT paper, COUNT(*) as tests, AVG(score) as avg FROM mock_tests WHERE status="completed" GROUP BY paper').fetchall()

    settings = dict(db.execute('SELECT key, value FROM settings').fetchall())

    return render_template('index.html',
        tests=tests, last_test=last_test, weak_topics=weak_topics, strong_topics=strong_topics,
        untested=untested, recent_errors=recent_errors, weekly_tests=weekly_tests,
        error_dist=error_dist, paper_perf=paper_perf, settings=settings)

@app.route('/test/setup', methods=['GET', 'POST'])
def test_setup():
    """Configure and start a new mock test"""
    db = get_db()
    if request.method == 'POST':
        paper = request.form.get('paper', 'II')
        num_qs = int(request.form.get('num_questions', 50))
        topics_str = request.form.get('topics', '')
        difficulty = request.form.get('difficulty', 'all')
        focus_weak = request.form.get('focus_weak') == 'on'

        query = 'SELECT q.*, t.name as topic_name FROM questions q JOIN topics t ON q.topic_id = t.id WHERE 1=1'
        params = []

        if paper != 'both':
            query += ' AND t.paper = ?'
            params.append(paper)
        if topics_str:
            topic_ids = [x.strip() for x in topics_str.split(',') if x.strip()]
            placeholders = ','.join('?' * len(topic_ids))
            query += f' AND t.id IN ({placeholders})'
            params.extend(topic_ids)
        if difficulty != 'all':
            query += ' AND q.difficulty = ?'
            params.append(difficulty)
        if focus_weak:
            weak_topic_ids = [str(t['topic_id']) for t in db.execute('SELECT topic_id FROM topic_mastery WHERE current_score < 60 OR current_score IS NULL').fetchall()]
            if weak_topic_ids:
                query += f' AND t.id IN ({",".join(weak_topic_ids)})'

        all_qs = db.execute(query, params).fetchall()
        if len(all_qs) < num_qs:
            num_qs = len(all_qs)
        selected = random.sample(list(all_qs), min(num_qs, len(all_qs)))

        test_id = db.execute('INSERT INTO mock_tests (started_at, paper, total_questions, max_score, status) VALUES (?,?,?,?,"in_progress")',
            (datetime.now().isoformat(), paper, len(selected), len(selected))).lastrowid
        db.commit()

        session['test_id'] = test_id
        session['questions'] = [dict(q) for q in selected]
        session['current_q'] = 0
        session['responses'] = {}
        session['q_start_time'] = time.time()

        return redirect(url_for('take_test'))

    topics = db.execute('SELECT * FROM topics ORDER BY paper, subject').fetchall()
    return render_template('test_setup.html', topics=topics)


@app.route('/test/take')
def take_test():
    """The actual test interface"""
    if 'test_id' not in session or 'questions' not in session or not session['questions']:
        session.pop('test_id', None)
        session.pop('questions', None)
        return redirect(url_for('test_setup'))
    return render_template('test.html',
        questions=session['questions'],
        current=session['current_q'],
        total=len(session['questions']),
        test_id=session['test_id'])


@app.route('/api/question/<int:idx>')
def get_question(idx):
    """API: Get question data (used by AJAX for single-question view)"""
    if 'questions' not in session or idx >= len(session['questions']):
        return jsonify({'error': 'Invalid index'}), 404
    q = session['questions'][idx]
    session['current_q'] = idx
    session['q_start_time'] = time.time()
    session.modified = True
    return jsonify({
        'id': q['id'], 'text': q['question_text'],
        'options': [q['option_a'], q['option_b'], q['option_c'], q['option_d']],
        'index': idx, 'total': len(session['questions']),
        'topic': q.get('topic_name', ''),
        'difficulty': q.get('difficulty', 'medium')
    })


@app.route('/api/submit_answer', methods=['POST'])
def submit_answer():
    """API: Submit answer with timing data"""
    data = request.json
    q_idx = data.get('question_index', session.get('current_q', 0))
    selected = data.get('selected_option')
    time_spent = data.get('time_spent', 0)

    if 'questions' not in session or q_idx >= len(session['questions']):
        return jsonify({'error': 'Invalid'}), 400

    q = session['questions'][q_idx]
    is_correct = (selected == q['correct_option'])

    session['responses'][str(q_idx)] = {
        'question_id': q['id'],
        'selected': selected,
        'correct': q['correct_option'],
        'is_correct': is_correct,
        'time_spent': time_spent,
        'topic_id': q.get('topic_id'),
        'topic_name': q.get('topic_name', '')
    }
    session['current_q'] = q_idx
    session.modified = True

    return jsonify({
        'is_correct': is_correct,
        'correct_option': q['correct_option'],
        'explanation': q.get('explanation', ''),
        'answered': len(session['responses']),
        'total': len(session['questions'])
    })


@app.route('/test/finish', methods=['POST'])
def finish_test():
    """End test and save all results"""
    if 'test_id' not in session:
        return redirect(url_for('index'))

    db = get_db()
    test_id = session['test_id']
    responses = session.get('responses', {})
    questions = session.get('questions', [])

    correct = sum(1 for r in responses.values() if r['is_correct'])
    total = len(questions)
    score = round((correct / total * 100) if total > 0 else 0, 1)
    total_time = sum(r.get('time_spent', 0) for r in responses.values())

    db.execute('UPDATE mock_tests SET completed_at=?, score=?, time_taken_sec=?, status="completed" WHERE id=?',
        (datetime.now().isoformat(), score, int(total_time), test_id))

    # Save responses and error log
    for q_idx_str, r in responses.items():
        q_idx = int(q_idx_str)
        error_type = None
        if not r['is_correct']:
            # Auto-categorize error type
            if r.get('time_spent', 0) < 10:
                error_type = 'time_pressure'
            elif r.get('time_spent', 0) > 120:
                error_type = 'concept_gap'
            else:
                error_type = 'concept_gap'

        db.execute('INSERT INTO test_responses (test_id, question_id, selected_option, is_correct, time_spent_sec, error_type) VALUES (?,?,?,?,?,?)',
            (test_id, r['question_id'], r['selected'], 1 if r['is_correct'] else 0, r.get('time_spent', 0), error_type))

        if not r['is_correct']:
            q = questions[q_idx]
            db.execute('INSERT INTO error_log (test_id, question_id, topic_id, selected_option, correct_option, error_type, created_at) VALUES (?,?,?,?,?,?,?)',
                (test_id, r['question_id'], r.get('topic_id'), r['selected'], r['correct'], error_type, datetime.now().isoformat()))

    # Update topic mastery
    topic_scores = {}
    for r in responses.values():
        tid = r.get('topic_id')
        if tid not in topic_scores:
            topic_scores[tid] = {'correct': 0, 'total': 0}
        topic_scores[tid]['total'] += 1
        if r['is_correct']: topic_scores[tid]['correct'] += 1

    for tid, scores in topic_scores.items():
        pct = round(scores['correct'] / scores['total'] * 100, 1)
        existing = db.execute('SELECT * FROM topic_mastery WHERE topic_id=?', (tid,)).fetchone()
        if existing:
            new_score = round((existing['current_score'] or 0) * 0.6 + pct * 0.4, 1) if existing['current_score'] else pct
            db.execute('UPDATE topic_mastery SET current_score=?, test_count=test_count+1, last_studied=?, status=? WHERE topic_id=?',
                (new_score, datetime.now().isoformat(), 'in_progress' if new_score < 70 else 'stable', tid))
        else:
            db.execute('INSERT INTO topic_mastery (topic_id, current_score, test_count, status, last_studied) VALUES (?,?,1,?,?)',
                (tid, pct, 'in_progress' if pct < 70 else 'stable', datetime.now().isoformat()))

    db.commit()

    # Store results for display
    session['last_result'] = {
        'test_id': test_id, 'score': score, 'correct': correct, 'total': total,
        'time_taken': int(total_time), 'paper': 'I' if len(questions) > 0 and questions[0].get('topic_name','').startswith('Raj') else 'II'
    }

    return redirect(url_for('results', test_id=test_id))

@app.route('/results/<int:test_id>')
def results(test_id):
    """Detailed test results page"""
    db = get_db()
    test = db.execute('SELECT * FROM mock_tests WHERE id=?', (test_id,)).fetchone()
    if not test: return redirect(url_for('index'))

    responses = db.execute('''
        SELECT tr.*, q.question_text, q.correct_option, q.explanation, q.option_a, q.option_b, q.option_c, q.option_d, t.name as topic_name, t.subject as subject
        FROM test_responses tr JOIN questions q ON tr.question_id = q.id
        JOIN topics t ON q.topic_id = t.id
        WHERE tr.test_id=? ORDER BY tr.id
    ''', (test_id,)).fetchall()

    # Timing analytics
    timings = [r['time_spent_sec'] for r in responses]
    avg_time = sum(timings) / len(timings) if timings else 0
    fastest = min(timings) if timings else 0
    slowest = max(timings) if timings else 0

    # Topic breakdown
    topic_breakdown = {}
    for r in responses:
        tn = r['topic_name']
        if tn not in topic_breakdown:
            topic_breakdown[tn] = {'correct': 0, 'total': 0, 'total_time': 0}
        topic_breakdown[tn]['total'] += 1
        topic_breakdown[tn]['total_time'] += r['time_spent_sec'] or 0
        if r['is_correct']: topic_breakdown[tn]['correct'] += 1

    # Error categorization
    errors = [r for r in responses if not r['is_correct']]
    error_types = {'concept_gap': 0, 'memory_lapse': 0, 'misread': 0, 'calculation': 0, 'time_pressure': 0}
    for e in errors:
        et = e['error_type'] or 'concept_gap'
        if et in error_types: error_types[et] += 1

    # Time segments
    early = [r for r in responses if r['id'] <= len(responses) * 0.33]
    mid = [r for r in responses if len(responses)*0.33 < r['id'] <= len(responses)*0.66]
    late = [r for r in responses if r['id'] > len(responses)*0.66]

    return render_template('results.html', test=test, responses=responses,
        avg_time=avg_time, fastest=fastest, slowest=slowest,
        topic_breakdown=topic_breakdown, errors=errors, error_types=error_types,
        early=early, mid=mid, late=late)

@app.route('/analytics')
def analytics():
    """Comprehensive analytics dashboard"""
    db = get_db()

    # Progress over time
    progress = [dict(r) for r in db.execute('SELECT id, date(completed_at) as d, paper, score, time_taken_sec FROM mock_tests WHERE status="completed" ORDER BY completed_at').fetchall()]

    # Topic mastery data for bar chart
    topics_data = [dict(r) for r in db.execute('''
        SELECT t.name, t.subject, tm.current_score, tm.test_count, tm.status, t.weightage
        FROM topic_mastery tm JOIN topics t ON tm.topic_id = t.id
        ORDER BY t.paper, t.subject
    ''').fetchall()]

    # Paper-wise comparison (last 5 tests each)
    paper1 = [dict(r) for r in db.execute('SELECT id, score, time_taken_sec, date(completed_at) as d FROM mock_tests WHERE paper="I" AND status="completed" ORDER BY completed_at DESC LIMIT 5').fetchall()]
    paper2 = [dict(r) for r in db.execute('SELECT id, score, time_taken_sec, date(completed_at) as d FROM mock_tests WHERE paper="II" AND status="completed" ORDER BY completed_at DESC LIMIT 5').fetchall()]

    # Error trends
    error_trends = [dict(r) for r in db.execute('''
        SELECT date(el.created_at) as d, el.error_type, COUNT(*) as cnt
        FROM error_log el GROUP BY d, el.error_type ORDER BY d
    ''').fetchall()]

    # Time-per-question trend
    time_trend = [dict(r) for r in db.execute('''
        SELECT mt.id, mt.paper, AVG(tr.time_spent_sec) as avg_time, mt.score
        FROM mock_tests mt JOIN test_responses tr ON mt.id = tr.test_id
        WHERE mt.status="completed" GROUP BY mt.id ORDER BY mt.completed_at
    ''').fetchall()]

    # Accuracy by difficulty
    difficulty_stats = [dict(r) for r in db.execute('''
        SELECT q.difficulty,
            COUNT(CASE WHEN tr.is_correct=1 THEN 1 END) as correct,
            COUNT(*) as total
        FROM test_responses tr JOIN questions q ON tr.question_id = q.id
        GROUP BY q.difficulty
    ''').fetchall()]

    # Weekly heatmap data (last 30 days)
    heatmap = []
    for i in range(30, -1, -1):
        d = (datetime.now() - timedelta(days=i)).strftime('%Y-%m-%d')
        day_data = db.execute('SELECT COUNT(*) as tests, AVG(score) as avg FROM mock_tests WHERE date(completed_at)=? AND status="completed"', (d,)).fetchone()
        heatmap.append({'date': d, 'tests': day_data['tests'], 'avg': round(day_data['avg'] or 0, 1)})

    # Settings
    settings = dict(db.execute('SELECT key, value FROM settings').fetchall())

    return render_template('analytics.html',
        progress=progress, topics_data=topics_data, paper1=paper1, paper2=paper2,
        error_trends=error_trends, time_trend=time_trend, difficulty_stats=difficulty_stats,
        heatmap=heatmap, settings=settings)

@app.route('/errorlog')
def error_log_view():
    """Error log browser"""
    db = get_db()
    page = request.args.get('page', 1, type=int)
    per_page = 25
    offset = (page - 1) * per_page

    topic_filter = request.args.get('topic')
    type_filter = request.args.get('type')
    resolved_filter = request.args.get('resolved', 'all')

    query = 'SELECT el.*, t.name as topic_name, q.question_text FROM error_log el JOIN topics t ON el.topic_id = t.id JOIN questions q ON el.question_id = q.id WHERE 1=1'
    params = []
    if topic_filter:
        query += ' AND el.topic_id=?'; params.append(topic_filter)
    if type_filter:
        query += ' AND el.error_type=?'; params.append(type_filter)
    if resolved_filter == 'yes':
        query += ' AND el.resolved=1'
    elif resolved_filter == 'no':
        query += ' AND el.resolved=0'

    total = db.execute(query.replace('SELECT el.*, t.name as topic_name, q.question_text', 'SELECT COUNT(*)'), params).fetchone()[0]
    errors = db.execute(query + ' ORDER BY el.created_at DESC LIMIT ? OFFSET ?', params + [per_page, offset]).fetchall()

    topics = db.execute('SELECT * FROM topics ORDER BY name').fetchall()

    return render_template('errorlog.html', errors=errors, topics=topics,
        total=total, page=page, per_page=per_page,
        topic_filter=topic_filter, type_filter=type_filter, resolved_filter=resolved_filter)

@app.route('/api/resolve_error', methods=['POST'])
def resolve_error():
    """Mark error as resolved"""
    data = request.json
    db = get_db()
    db.execute('UPDATE error_log SET resolved=1, root_cause=? WHERE id=?', (data.get('root_cause', ''), data['error_id']))
    db.commit()
    return jsonify({'status': 'ok'})

@app.route('/api/redo_error', methods=['POST'])
def redo_error():
    """Record redo score for spaced repetition"""
    data = request.json
    db = get_db()
    field = 'redo_1_score' if data.get('attempt') == 1 else 'redo_2_score'
    db.execute(f'UPDATE error_log SET {field}=? WHERE id=?', (data['score'], data['error_id']))
    db.commit()
    return jsonify({'status': 'ok'})

@app.route('/api/settings', methods=['POST'])
def update_settings():
    """Update user settings"""
    data = request.json
    db = get_db()
    for k, v in data.items():
        db.execute('INSERT OR REPLACE INTO settings (key, value) VALUES (?,?)', (k, str(v)))
    db.commit()
    return jsonify({'status': 'ok'})

@app.route('/api/study_session', methods=['POST'])
def log_study_session():
    """Log a study session"""
    data = request.json
    db = get_db()
    db.execute('INSERT INTO study_sessions (date, topic_id, duration_min, mcqs_solved, score, notes) VALUES (?,?,?,?,?,?)',
        (datetime.now().isoformat(), data['topic_id'], data['duration'], data['mcqs'], data.get('score', 0), data.get('notes', '')))
    db.execute('UPDATE topic_mastery SET study_hours = study_hours + ? WHERE topic_id = ?', (data['duration']/60.0, data['topic_id']))
    db.commit()
    return jsonify({'status': 'ok'})

# ─── Doubt Counter — AI Deep Dive Engine ────────────────────

NOTES_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'notes')

NOTES_FILES = {
    'History': [
        'rajasthan-history-culture-notes.md',
        'exam-quick-revision-notes.md',
        'syllabus-analysis.md',
    ],
    'Geography': [
        'rajasthan-geography-notes.md',
        'exam-quick-revision-notes.md',
        'syllabus-analysis.md',
    ],
    'Polity': [
        'rajasthan-studies-notes.md',
        'exam-quick-revision-notes.md',
    ],
    'CS': [
        'computer-anudeshak-2022-paper1-solutions.md',
        'yct-computer-anudeshak-practice-sets.md',
        'syllabus-analysis.md',
    ],
    'Science': [
        'police-constable-2022-paper-solutions.md',
        'exam-quick-revision-notes.md',
    ],
    'Current': ['exam-quick-revision-notes.md', 'syllabus-analysis.md'],
    'Reasoning': ['exam-quick-revision-notes.md'],
    'Quant': ['exam-quick-revision-notes.md'],
}
SUPPLEMENTARY_FILES = [
    'rssb-exam-answer-keys-compilation.md',
    'syllabus-analysis.md',
]

GEMINI_CLI = shutil.which('gemini') or os.path.expanduser('~/.nvm/versions/node/v20.20.2/bin/gemini')

# In-memory chat history (single-user localhost)
_chat_histories = {}

def get_notes_context(topic_name, subject, question_text):
    """Search relevant markdown files for context about this question."""
    files_to_search = list(set(
        NOTES_FILES.get(subject, []) + SUPPLEMENTARY_FILES
    ))
    candidates = []

    for fname in files_to_search:
        fpath = os.path.join(NOTES_DIR, fname)
        if not os.path.exists(fpath):
            continue
        try:
            content = open(fpath, 'r', encoding='utf-8', errors='ignore').read()
        except Exception:
            continue

        # Split into sections by ## headings
        sections = re.split(r'\n(?=##\s)', content)
        for sec in sections:
            if len(sec.strip()) < 40:
                continue
            # Score by keyword overlap
            keywords = set(re.findall(r'\w+', (topic_name + ' ' + question_text).lower()))
            sec_words = set(re.findall(r'\w+', sec.lower()))
            score = len(keywords & sec_words)
            if score > 0:
                candidates.append((score, sec[:2000]))

    candidates.sort(key=lambda x: x[0], reverse=True)
    top = [c[1] for c in candidates[:5]]
    context = '\n\n---\n\n'.join(top)
    return context[:4000]

def call_gemini(prompt, timeout=60):
    """Call Gemini CLI and return response text.
    Uses polling instead of timeout-based waits to avoid proot signal issues."""
    import threading
    try:
        p = subprocess.Popen(
            [GEMINI_CLI, '--skip-trust', '-p', prompt],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
            env={**os.environ, 'LANG': 'en_US.UTF-8'}
        )
        output = [None, None]
        done = [False]

        def read_pipes():
            try:
                output[0], output[1] = p.communicate()
            except SystemExit:
                pass
            except Exception:
                pass
            done[0] = True

        t = threading.Thread(target=read_pipes)
        t.start()
        deadline = time.time() + timeout
        while not done[0] and time.time() < deadline:
            time.sleep(0.1)

        if not done[0]:
            p.kill()
            t.join()
            return 'Analysis timed out. Try a simpler question or try again.'

        stdout = output[0] or ''
        stderr_out = output[1] or ''
        lines = stdout.strip().split('\n')
        response = '\n'.join(
            l for l in lines
            if not l.startswith('Ripgrep') and not l.startswith('Falling back') and not l.startswith('Warning:')
        ).strip()
        return response or stderr_out.strip() or 'Analysis unavailable.'
    except Exception as e:
        return f'Analysis error: {str(e)}'

@app.route('/api/doubt/deep-dive', methods=['POST'])
def doubt_deep_dive():
    """Generate AI analysis for a question using study notes + Gemini."""
    data = request.json
    question_id = data.get('question_id')
    test_id = data.get('test_id')

    if not question_id:
        return jsonify({'error': 'question_id is required'}), 400

    cache_key = f'deep_dive:{question_id}:{test_id}'
    db = get_db()
    cached = db.execute('SELECT response_json FROM doubt_cache WHERE cache_key=?', (cache_key,)).fetchone()
    if cached:
        return jsonify({'analysis': json.loads(cached['response_json']), 'cached': True})

    # Get question + topic info
    q = db.execute('''
        SELECT q.*, t.name as topic_name, t.subject
        FROM questions q JOIN topics t ON q.topic_id = t.id
        WHERE q.id=?
    ''', (question_id,)).fetchone()
    if not q:
        return jsonify({'error': 'Question not found'}), 404

    # Get notes context
    notes_ctx = get_notes_context(q['topic_name'], q['subject'], q['question_text'])

    # Build prompt
    storyline_instruction = ''
    if q['subject'] == 'History':
        storyline_instruction = '4. **Storyline** — A short memorable story or mnemonic (2-3 sentences) that makes these facts easy to recall.'

    prompt = f'''You are an expert tutor for Rajasthan competitive exams (Computer Anudeshak / Computer Instructor). Analyze this question deeply.

QUESTION: {q['question_text'][:500]}
TOPIC: {q['topic_name']}
SUBJECT: {q['subject']}
CORRECT ANSWER: {q['correct_option']}
OFFICIAL EXPLANATION: {q['explanation'] or 'None provided'}

RELEVANT STUDY NOTES:
{notes_ctx[:3000]}

Give a structured response with these exact sections:
1. **Concept Explanation** — 2-3 paragraphs explaining the concept in depth. Include background, context, and why the correct answer is right.
2. **Key Facts** — 3-5 bullet points of must-remember facts related to this topic.
3. **Exam Tips** — How this topic is typically tested, common traps, and what similar questions to expect.
{storyline_instruction}

Use markdown formatting. Keep each section concise but thorough. IMPORTANT: Write the ENTIRE response in English only. Do NOT use Hindi or any other language.'''

    response = call_gemini(prompt)

    # Parse response into structured sections
    analysis = {
        'explanation': '',
        'key_facts': [],
        'exam_tips': '',
        'storyline': '',
    }

    # Try splitting by numbered section headers (handles both ### 1. and 1. formats)
    sections = re.split(r'\n(?=(?:###\s+)?\d+\.\s*(?:Concept|Key|Exam|Story))', response, flags=re.IGNORECASE)
    if len(sections) <= 1:
        # No numbered sections found; try splitting by --- separator
        sections = response.split('\n---\n')

    for sec in sections:
        sec = sec.strip()
        heading_lower = sec.split('\n')[0].lower()

        if 'concept explanation' in heading_lower or 'concept' in heading_lower:
            analysis['explanation'] = re.sub(r'^(?:###\s+)?\d+\.\s*Concept[^)]*\)?\s*\n*', '', sec).strip()
        elif 'key fact' in heading_lower:
            body = re.sub(r'^(?:###\s+)?\d+\.\s*Key\s*Facts?[^)]*\)?\s*\n*', '', sec).strip()
            lines = [l for l in body.split('\n') if l.strip() and not l.strip().startswith('---')]
            analysis['key_facts'] = [re.sub(r'^[*-]\s*', '', l).strip() for l in lines if l.strip()]
        elif 'exam tip' in heading_lower:
            analysis['exam_tips'] = re.sub(r'^(?:###\s+)?\d+\.\s*Exam\s*Tips?[^)]*\)?\s*\n*', '', sec).strip()
        elif 'storyline' in heading_lower or 'story' in heading_lower:
            analysis['storyline'] = re.sub(r'^(?:###\s+)?\d+\.\s*Storyline[^)]*\)?\s*\n*', '', sec).strip()

    # If parsing failed, use raw response as explanation
    if not analysis['explanation'] and not analysis['key_facts']:
        analysis['explanation'] = response

    # Cache it
    db.execute('INSERT INTO doubt_cache (cache_key, response_json, created_at) VALUES (?,?,?)',
        (cache_key, json.dumps(analysis), datetime.now().isoformat()))
    db.commit()

    return jsonify({'analysis': analysis, 'cached': False})

@app.route('/api/doubt/chat', methods=['POST'])
def doubt_chat():
    """Follow-up chat about a question topic."""
    data = request.json
    question_id = data.get('question_id')
    test_id = data.get('test_id')
    message = (data.get('message') or '').strip()

    if not question_id or not message:
        return jsonify({'error': 'question_id and message are required'}), 400

    db = get_db()
    q = db.execute('''
        SELECT q.*, t.name as topic_name, t.subject
        FROM questions q JOIN topics t ON q.topic_id = t.id
        WHERE q.id=?
    ''', (question_id,)).fetchone()
    if not q:
        return jsonify({'error': 'Question not found'}), 404

    # Get cached analysis for context
    cache_key = f'deep_dive:{question_id}:{test_id}'
    cached = db.execute('SELECT response_json FROM doubt_cache WHERE cache_key=?', (cache_key,)).fetchone()
    analysis_text = ''
    if cached:
        analysis_text = cached['response_json'][:2000]

    # Chat history
    chat_id = f'{question_id}:{test_id}'
    if chat_id not in _chat_histories:
        _chat_histories[chat_id] = []
    history = _chat_histories[chat_id][-6:]  # Last 6 messages

    history_text = '\n'.join(f"{'User' if h['role'] == 'user' else 'Tutor'}: {h['content']}" for h in history)

    prompt = f'''You are an expert tutor helping with Rajasthan Computer Anudeshak exam preparation.

TOPIC: {q['topic_name']}
SUBJECT: {q['subject']}
QUESTION: {q['question_text'][:300]}

PREVIOUS ANALYSIS SUMMARY:
{analysis_text[:1500]}

CONVERSATION SO FAR:
{history_text}

User's new question: {message}

Provide a clear, exam-focused answer. Reference study material and Rajasthan-specific context where relevant. Keep it 2-3 paragraphs. Use markdown. IMPORTANT: Write in English only. Do NOT use Hindi or any other language.'''

    response = call_gemini(prompt, timeout=45)

    # Update history
    _chat_histories[chat_id].append({'role': 'user', 'content': message})
    _chat_histories[chat_id].append({'role': 'assistant', 'content': response})
    # Trim history
    if len(_chat_histories[chat_id]) > 20:
        _chat_histories[chat_id] = _chat_histories[chat_id][-20:]

    return jsonify({'response': response})

# ─── Initialize ───────────────────────────────────────────────
if __name__ == '__main__':
    init_db()
    try: seed_data()
    except: pass
    print("\n╔══════════════════════════════════════════════════════╗")
    print("║   Computer Anudeshak Exam Prep Platform v1.0       ║")
    print("║   Running at: http://localhost:5050                 ║")
    print("║   Diagnostic-First Method Engine                   ║")
    print("╚══════════════════════════════════════════════════════╝\n")
    app.run(debug=False, port=5050, host='127.0.0.1')
