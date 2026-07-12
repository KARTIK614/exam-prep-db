"""AI helpers — notes lookup + Gemini CLI wrapper."""
import os
import re
import time
import subprocess
import threading

from ai_config import NOTES_DIR, NOTES_FILES, SUPPLEMENTARY_FILES, GEMINI_CLI


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

        sections = re.split(r'\n(?=##\s)', content)
        for sec in sections:
            if len(sec.strip()) < 40:
                continue
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
    """Call Gemini CLI and return response text. Uses polling to avoid signal issues under proot."""
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


# In-memory chat history keyed by (question_id, test_id).
# Single-user assumption; not persisted across restarts.
_chat_histories = {}


def get_chat_history(chat_id):
    return _chat_histories.setdefault(chat_id, [])


def append_chat(chat_id, role, content, max_len=20):
    hist = get_chat_history(chat_id)
    hist.append({'role': role, 'content': content})
    if len(hist) > max_len:
        _chat_histories[chat_id] = hist[-max_len:]
