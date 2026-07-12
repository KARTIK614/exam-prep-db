#!/usr/bin/env python3
import os
import subprocess
import sqlite3
import re
import sys
import time

# Configuration
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, 'data', 'exam_prep.db')
# Try to find the PDF in several common locations
PDF_LOCATIONS = [
    os.path.join(os.path.dirname(BASE_DIR), 'YCT Computer Anudeshak Practice Set 2022(www.freestudymaterial247.co.in) (1).pdf'),
    '/sdcard/YCT Computer Anudeshak.pdf',
    os.path.join(BASE_DIR, 'yct_practice.pdf')
]
PDF_PATH = next((p for p in PDF_LOCATIONS if os.path.exists(p)), PDF_LOCATIONS[0])
PAGES_DIR = os.path.join(BASE_DIR, 'yct_pages')

# Find Gemini CLI binary
GEMINI_BIN = subprocess.run(['which', 'gemini'], capture_output=True, text=True).stdout.strip()
if not GEMINI_BIN:
    GEMINI_BIN = '/home/pandit/.nvm/versions/node/v20.20.2/bin/gemini' # Fallback

TOPIC_MAP = {
    'General Science': 18,
    'Biology': 17,
    'Physics': 18,
    'Chemistry': 18,
    'History': 25, # Using 25 as catch-all for non-Rajasthan history
    'Geography': 25,
    'Polity': 14,
    'Computer Fundamentals': 25,
    'Number Systems': 26,
    'MS Office': 27,
    'DBMS': 33,
    'Operating System': 34,
    'Networking': 35,
    'Web Technologies': 37,
    'SDLC': 38,
    'Management': 38,
    'IoT': 39,
    'Computer Organization': 41,
    'Electrical': 18, # Mapping technical subjects to Science for now
    'Mechanical': 18,
    'Economics': 25
}

def extract_pages(start, end):
    print(f"[*] Extracting pages {start} to {end}...")
    os.makedirs(PAGES_DIR, exist_ok=True)
    cmd = [
        'pdftoppm', '-jpeg', '-r', '200',
        '-f', str(start), '-l', str(end),
        PDF_PATH, os.path.join(PAGES_DIR, f'page_{start}_{end}')
    ]
    subprocess.run(cmd, check=True)
    
    # Rename files to standard page_N.jpg
    for i in range(start, end + 1):
        old_name = os.path.join(PAGES_DIR, f'page_{start}_{end}-{i:03d}.jpg')
        if os.path.exists(old_name):
            new_name = os.path.join(PAGES_DIR, f'page_{i}.jpg')
            os.rename(old_name, new_name)

def transcribe_page(page_num):
    img_path = os.path.join(PAGES_DIR, f'page_{page_num}.jpg')
    print(f"[*] Transcribing page {page_num}...")
    
    prompt = f"Transcribe ALL multiple choice questions from this image: {img_path}. Use EXACTLY this pipe-delimited format, one question per line: Q_num|question_text|option_A|option_B|option_C|option_D|correct_letter. Preserve the language (Hindi/English) as in the image. Do not include any other text."
    
    cmd = [GEMINI_BIN, '-p', prompt]
    result = subprocess.run(cmd, capture_output=True, text=True)
    
    if result.returncode != 0:
        print(f"[!] Error transcribing page {page_num}: {result.stderr}")
        return []
    
    return result.stdout.strip().split('\n')

def parse_line(line):
    parts = line.strip().split('|')
    if len(parts) >= 7:
        return {
            'qnum': parts[0].strip(),
            'text': parts[1].strip(),
            'a': parts[2].strip(),
            'b': parts[3].strip(),
            'c': parts[4].strip(),
            'd': parts[5].strip(),
            'ans': parts[6].strip()[-1].upper() if parts[6].strip() else ''
        }
    return None

def ingest_questions(questions, topic_id):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    count = 0
    for q in questions:
        if not q: continue
        try:
            # Check for duplicates
            exists = cursor.execute('SELECT id FROM questions WHERE question_text = ?', (q['text'],)).fetchone()
            if exists:
                continue
                
            cursor.execute('''
                INSERT INTO questions (topic_id, question_text, option_a, option_b, option_c, option_d, correct_option, source)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ''', (topic_id, q['text'], q['a'], q['b'], q['c'], q['d'], q['ans'], 'yct-practice-set'))
            count += 1
        except Exception as e:
            print(f"[!] DB Error: {e}")
            
    conn.commit()
    conn.close()
    return count

def main():
    if len(sys.argv) < 4:
        print("Usage: ingest_pipeline.py <start_page> <end_page> <topic_id>")
        sys.exit(1)
        
    start = int(sys.argv[1])
    end = int(sys.argv[2])
    topic_id = int(sys.argv[3])
    
    # Optional: Extract if images don't exist
    missing = False
    for i in range(start, end + 1):
        if not os.path.exists(os.path.join(PAGES_DIR, f'page_{i}.jpg')):
            missing = True
            break
    
    if missing:
        extract_pages(start, end)
        
    total_ingested = 0
    for i in range(start, end + 1):
        lines = transcribe_page(i)
        parsed = [parse_line(l) for l in lines if '|' in l]
        ingested = ingest_questions(parsed, topic_id)
        print(f"[+] Page {i}: Ingested {ingested}/{len(parsed)} questions.")
        total_ingested += ingested
        # Sleep to avoid rate limits if any
        time.sleep(2)
        
    print(f"\n[***] Finished! Total Ingested: {total_ingested}")

if __name__ == '__main__':
    main()
