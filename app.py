import streamlit as st
import json
import os
import google.generativeai as genai
from PIL import Image
from gtts import gTTS
import io
import re
import gspread
import PyPDF2

# --- GOOGLE SHEETS ENGINE ---
@st.cache_resource
def connect_to_sheets():
    creds_dict = json.loads(st.secrets["GOOGLE_CREDENTIALS"])
    gc = gspread.service_account_from_dict(creds_dict)
    return gc.open("Christine Student Memory")

try:
    workbook = connect_to_sheets()
    sheet = workbook.sheet1
    syllabus_sheet = workbook.worksheet("Syllabus")
except Exception as e:
    st.error(f"Could not connect to Google Sheets. Check your exact spreadsheet name: {e}")

# --- NEW: SYLLABUS LOADER ---
def load_syllabus():
    try:
        records = syllabus_sheet.get_all_records()
        curriculum = {}
        for row in records:
            course = str(row.get("Course", "")).strip()
            topic = str(row.get("Topic", "")).strip()
            if course and topic:
                if course not in curriculum:
                    curriculum[course] = []
                curriculum[course].append(topic)
        return curriculum
    except Exception:
        return {"General Study": ["General Topic"]}

def load_data():
    db = {}
    try:
        rows = sheet.get_all_values()
        if len(rows) <= 1:
            return db
        
        for row in rows[1:]:
            # UPGRADED TO 6 COLUMNS FOR THE VAULT
            while len(row) < 6:
                row.append("")
                
            name_col = str(row[0]).strip().lower()
            summary_col = str(row[1]).strip()
            history_col = str(row[2]).strip()
            age_col = str(row[3]).strip()
            topic_col = str(row[4]).strip()
            vault_col = str(row[5]).strip() # THE NEW VAULT COLUMN
            
            if name_col and name_col not in db:
                try:
                    hist = json.loads(history_col)
                except:
                    hist = []
                    
                student_age = None if (age_col == "" or age_col == "0") else age_col
                
                db[name_col] = {
                    "summary": summary_col, 
                    "history": hist, 
                    "age": student_age, 
                    "last_topic": topic_col,
                    "file_vault": vault_col # ADDED VAULT TO DB DICTIONARY
                }
        return db
    except Exception as e:
        st.error(f"⚠️ Database connection paused. Please refresh the page. (System code: {e})")
        st.stop() 

def save_current_student(name, data):
    summary = data.get("summary", "")
    full_history = data.get("history", [])
    recent_history = full_history[-10:] if len(full_history) > 10 else full_history
    hist_str = json.dumps(recent_history)
    age = data.get("age", "") 
    last_topic = data.get("last_topic", "")
    file_vault = data.get("file_vault", "") # GRAB VAULT DATA
    
    try:
        cell = sheet.find(name, in_column=1)
        sheet.update_cell(cell.row, 2, summary)
        sheet.update_cell(cell.row, 3, hist_str)
        sheet.update_cell(cell.row, 4, age)
        sheet.update_cell(cell.row, 5, last_topic)
        sheet.update_cell(cell.row, 6, file_vault) # SAVE VAULT DATA
    except Exception:
        sheet.append_row([name, summary, hist_str, age, last_topic, file_vault])

# --- CONFIGURATION ---
st.set_page_config(page_title="Christine AI Tutor", page_icon="🎓", layout="wide")

PRIMARY_MODEL = "gemini-2.5-flash"
FALLBACK_MODEL = "gemini-2.5-flash-lite"

api_key = st.secrets.get("GEMINI_API_KEY", None)
if not api_key:
    api_key = st.sidebar.text_input("Enter Google Gemini API Key", type="password")

# ADDED FILE VAULT TO HER BRAIN
def get_system_instruction(age, subject, history_summary, file_vault=""):
    vault_text = f"\n\nSAVED DOCUMENT VAULT:\nThe student has saved the following document to memory so they don't have to re-upload it. Use this as your primary source material if they ask to continue working on it:\n{file_vault}" if file_vault else ""

    return f"""
    You are "Christine," an empathetic AI Educational Assistant and expert memory coach for students aged 11-18.

    USER PROFILE:
    Age: {age}
    Current Topic: {subject}
    Past Context (Bookmark & Gaps): {history_summary}
    {vault_text}

    CURRICULUM GOAL:
    PROACTIVELY guide the student through the "Current Topic".
    CRITICAL RULE: Read "Past Context" to see what they mastered. NEVER re-teach mastered concepts.
    Pick up exactly where the "Bookmark" leaves off and determine the NEXT logical concept.

    TEST-FIRST APPROACH: Do not just explain the next concept. You must test their knowledge on it FIRST before teaching.

    CORE GUIDELINES:
    1. **Strict Brevity & Slow Processing:** Responses must be extremely concise. Chunk complex ideas. Use short bullet points. NEVER output walls of text. Keep your total response as short as possible.
    2. **Tone:** Patient, encouraging, non-judgmental. Make learning feel like a fun, creative game. Never rush the student.
    3. **Voice Input Rule:** NEVER start your response with a microphone emoji, "Voice response," or a transcript of what the user said. Just answer directly.
    4. **Image Analysis:** The user may upload a photo of written work. Transcribe it, analyze based on Age {age} standards, provide short "Glow" and "Grow" feedback. Scaffold answers strictly ONE step at a time.
    5. **Safety & Exam Prep:** Do not answer *active/live* test questions to help a student cheat.
    6. **The Memory Rule:** NEVER use the Kevin Horsley memory techniques by default. Always teach standard academic concepts first.
    7. **STRICT GUARDRAILS:** Keep the student focused on the "Current Topic" ({subject}). HOWEVER, if the recent chat history involves an uploaded image or file, this is a SYSTEM OVERRIDE. You must pause the current topic and completely focus on reviewing or quizzing them on that uploaded material until the exercise is completely finished.
    8. **ENGLISH & LITERATURE ANALYSIS:** If the student uploads a text or reading assignment, act as a Socratic English teacher. Focus on extracting meaning, analyzing connotations, exploring literary devices (imagery, metaphors, personification), and improving their vocabulary. NEVER write analytical paragraphs (like PEE/PEEL) for them; scaffold their writing strictly one sentence at a time.
    9. **DYNAMIC VISUAL LEARNING:** You are now a highly visual tutor. Whenever you are introducing a new historical event, a science concept, a character from a book, or a real-world object, you MUST generate a visual aid for the student. Do this by secretly injecting this exact Markdown format into your response: 
    ![Image](https://image.pollinations.ai/prompt/A%20highly%20detailed%20educational%20illustration%20of%20[YOUR_DESCRIPTION_HERE]?width=800&height=400&nologo=true)
    Replace [YOUR_DESCRIPTION_HERE] with a highly descriptive prompt. YOU MUST REPLACE ALL SPACES IN THE URL WITH %20. Never ask the student if they want to see an image; just embed it directly above your explanation.
    10. **MATH & PHYSICS VISUALS (THE ASSET VAULT):** If the student is asking about math, geometry, or physics, NEVER use the AI image generator from Rule 9. For equations, use perfect LaTeX formatting (e.g., $x = y^2$). If the topic requires a visual diagram (like charts, weights, or graphs), you MUST use one of the approved, mathematically accurate images from our Asset Vault by injecting its exact Markdown link into your response:
    - Balance Scale / Mass: `![Balance Scale](https://upload.wikimedia.org/wikipedia/commons/thumb/a/a2/Balance_scale.png/400px-Balance_scale.png)`
    - Coordinate Grid: `![Coordinate Grid](https://upload.wikimedia.org/wikipedia/commons/thumb/9/91/Cartesian_coordinate_system.svg/400px-Cartesian_coordinate_system.svg.png)`
    - Pie Chart: `![Pie Chart](https://upload.wikimedia.org/wikipedia/commons/thumb/b/b4/Pie_charts_of_populations_of_English_native_speakers.png/400px-Pie_charts_of_populations_of_English_native_speakers.png)`
    - Protractor / Angles: `![Protractor](https://upload.wikimedia.org/wikipedia/commons/thumb/c/cd/Protractor1.svg/400px-Protractor1.svg.png)`
    If an appropriate image is not in this vault, do not generate one. Simply describe it clearly or use LaTeX.
    
    MODES OF OPERATION:
    A) TEST-FIRST TEACHING MODE (DEFAULT):
    1. Ask ONE short, diagnostic question about the next concept.
    2. STOP and wait for the student to answer. Do not give away the answer.
    3. If correct: Praise, confirm mastery, test the NEXT concept.
    4. If incorrect/help needed: Explain in 1-to-2 sentences using 3 or 4 key facts.
    5. Proactively ask: "Would you like me to teach you a quick memory trick to lock this in?"
    
    B) MEMORY COACHING MODE:
    1. Write vivid, bizarre image descriptions using the SEE Principle (1-2 sentences).
    2. Apply the Number-Rhyme Peg System or Journey Method.
    
    C) EXAM PREP (BATCH QUIZ MODE):
    1. If the student explicitly asks for a quiz or a specific number of questions (e.g., "give me 40 questions"), this is a SYSTEM OVERRIDE of the brevity rule.
    2. You must generate the EXACT number of questions requested in a numbered list all at once. Do not ask them one by one.
    3. STOP and wait for the student to answer them.
    4. Grade their answers with "Glow" and "Grow" feedback.
    """
    
def convert_history_for_gemini(history):
    gemini_history = []
    for msg in history:
        role = "user" if msg["role"] == "user" else "model"
        content = msg["content"]
        if isinstance(content, str):
            gemini_history.append({"role": role, "parts": [content]})
    return gemini_history

# --- MAIN APP UI ---
st.title("🎓 Christine: AI Tutor")

# --- SESSION STATE SETUP ---
if "camera_open" not in st.session_state: st.session_state.camera_open = False
if "captured_image" not in st.session_state: st.session_state.captured_image = None
if "last_processed_file_id" not in st.session_state: st.session_state.last_processed_file_id = None
if "unsummarized_messages" not in st.session_state: st.session_state.unsummarized_messages = 0
if "last_processed_audio_id" not in st.session_state: st.session_state.last_processed_audio_id = None
    
raw_username = st.text_input("Please enter your first name to begin:", key="username_input")
username = raw_username.strip().lower() if raw_username else ""

if username and api_key:
    genai.configure(api_key=api_key)
    
    if "user_data" not in st.session_state or st.session_state.get("current_user") != username:
        with st.spinner("Downloading profile..."):
            db = load_data()
            if username not in db:
                st.session_state.user_data = {"age": None, "history": [], "summary": "New student.", "file_vault": ""}
            else:
                st.session_state.user_data = db[username]
                saved_topic = db[username].get("last_topic", "a new topic")
                if saved_topic == "": saved_topic = "a new topic"
                
                st.session_state.user_data["history"] = [{
                    "role": "model", 
                    "content": f"Welcome back, {username.title()}! I've reviewed my notes, and it looks like we were working on **{saved_topic}**. Are you ready to pick up exactly where we left off, or do you want to switch topics?"
                }]
            st.session_state.current_user = username

    user_data = st.session_state.user_data

    if not user_data.get("age"):
        st.info(f"Hi {username}! I'm Christine. Let's get set up.")
        col1, col2 = st.columns(2)
        with col1: age_input = st.number_input("How old are you?", min_value=11, max_value=18, step=1)
        with col2: subject_input = st.text_input("What subject are we doing today?")
            
        if st.button("Start Learning"):
            user_data["age"] = age_input
            user_data["history"].append({"role": "model", "content": f"Hello {username}! I'm ready to help you with {subject_input}. How can we start?"})
            save_current_student(username, user_data)
            st.rerun()
    else:
        # --- SIDEBAR TOOLS ---
        st.sidebar.title(f"👤 {username}'s Space")
        
         # --- TEMPORARY DIAGNOSTIC BUTTON ---
        if st.sidebar.button("🔍 Find My Models"):
            with st.spinner("Checking Google's servers..."):
                try:
                    available = [m.name for m in genai.list_models() if 'generateContent' in m.supported_generation_methods]
                    st.sidebar.success("Found them! Use one of these names:")
                    for m in available:
                        st.sidebar.code(m.replace("models/", ""))
                except Exception as e:
                    st.sidebar.error(f"Error checking models: {e}")
        # -----------------------------------
    
        st.sidebar.caption("🗺️ Your Learning Map")
        syllabus_data = load_syllabus()
        course_list = list(syllabus_data.keys())
        
        saved_course_topic = user_data.get("last_topic", "")
        if ":" in saved_course_topic:
            default_course, default_topic = saved_course_topic.split(":", 1)
            default_course, default_topic = default_course.strip(), default_topic.strip()
        else:
            default_course = course_list[0] if course_list else ""
            default_topic = ""

        course_index = course_list.index(default_course) if default_course in course_list else 0
        selected_course = st.sidebar.selectbox("Course:", course_list, index=course_index)

        topic_list = syllabus_data.get(selected_course, ["General Topic"])
        topic_index = topic_list.index(default_topic) if default_topic in topic_list else 0
        selected_topic = st.sidebar.selectbox("Current Topic:", topic_list, index=topic_index)
        
        current_subject = f"{selected_course}: {selected_topic}"
      
        if current_subject != user_data.get("last_topic"):
            is_active_switch = user_data.get("last_topic") != ""
            user_data["last_topic"] = current_subject
            save_current_student(username, user_data)
            
            if is_active_switch:
                if st.session_state.unsummarized_messages > 0:
                    st.session_state.unsummarized_messages = 14 
                
                st.session_state.auto_submit_topic = current_subject
                st.rerun()

        st.sidebar.markdown("---")
        voice_on = st.sidebar.toggle("🔊 Read Christine's answers out loud")
        
        # --- MASTERY PERCENTAGE TRACKER ---
        st.sidebar.divider()
        st.sidebar.markdown(f"### 🏆 {selected_topic} Brain Power")

        dossier_text = user_data["summary"] if user_data.get("summary") else ""
        safe_topic = re.escape(selected_topic)

        mastered_count = len(re.findall(rf'\[{safe_topic}\]\s*mastered', dossier_text, re.IGNORECASE))
        gap_count = len(re.findall(rf'\[{safe_topic}\]\s*gap', dossier_text, re.IGNORECASE))
        total_tracked = mastered_count + gap_count

        if total_tracked > 0:
            mastery_percentage = int((mastered_count / total_tracked) * 100)
        else:
            mastery_percentage = 0

        st.sidebar.progress(mastery_percentage / 100.0)
        
        # --- CELEBRATION TRIGGER ---
        if mastery_percentage == 100 and st.session_state.get("celebrated_topic") != selected_topic:
            st.balloons() 
            st.session_state["celebrated_topic"] = selected_topic

        st.sidebar.metric(label=f"Topic Mastery", value=f"{mastery_percentage}%")
        st.sidebar.caption(f"**{mastered_count}** Mastered | **{gap_count}** Gaps in {selected_topic}")
        
        st.sidebar.markdown("---")
        
        st.sidebar.header("📸 Submit Work")
        image_action = st.sidebar.radio(
            "Step 1: What should Christine do?",
            ["Review my work for mistakes", "Quiz me on this content", "Guide me through this English text"]
        )
        
        st.sidebar.caption("Step 2: Upload or snap your photo/document:")
        file_input = st.sidebar.file_uploader("Upload File", type=['png', 'jpg', 'jpeg', 'webp', 'pdf'])
        st.sidebar.write("OR")
        
        if st.session_state.captured_image:
            st.sidebar.image(st.session_state.captured_image, caption="Ready to send", use_container_width=True)
            if st.sidebar.button("🗑️ Discard & Retake"):
                st.session_state.captured_image = None
                st.session_state.camera_open = True
                st.rerun()
        else:
            if not st.session_state.camera_open:
                if st.sidebar.button("📸 Open Camera"):
                    st.session_state.camera_open = True
                    st.rerun()
            else:
                if st.sidebar.button("❌ Close Camera"):
                    st.session_state.camera_open = False
                    st.rerun()
                cam_input = st.sidebar.camera_input("Take Photo")
                if cam_input:
                    st.session_state.captured_image = Image.open(cam_input)
                    st.session_state.camera_open = False
                    st.rerun()

        # ---------------------------------------------------------
        # --- NEW: THE DOCUMENT VAULT UI ---
        # ---------------------------------------------------------
        st.sidebar.markdown("---")
        st.sidebar.header("🗄️ Document Vault")
        
        current_vault = user_data.get("file_vault", "")
        if current_vault:
            st.sidebar.success("✅ A document is saved in memory for this session.")
            with st.sidebar.expander("View Saved Document"):
                st.write(current_vault)
            if st.sidebar.button("🗑️ Clear Vault"):
                user_data["file_vault"] = ""
                save_current_student(username, user_data)
                st.rerun()
                
        elif file_input or st.session_state.captured_image:
            st.sidebar.info("Upload detected. Do you want Christine to memorize this so you don't have to upload it next time?")
            if st.sidebar.button("💾 Memorize Document"):
                with st.spinner("Extracting text to Vault..."):
                    try:
                        extracted_text = ""
                        
                        # IF IT IS A PDF: Instantly extract text using Python
                        if file_input and file_input.name.lower().endswith('.pdf'):
                            pdf_reader = PyPDF2.PdfReader(file_input)
                            for page in range(len(pdf_reader.pages)):
                                page_text = pdf_reader.pages[page].extract_text()
                                if page_text:
                                    extracted_text += f"\n--- PAGE {page + 1} ---\n" + page_text
                                    
                        # IF IT IS AN IMAGE: Use the AI to transcribe it normally
                        else:
                            vault_model = genai.GenerativeModel(model_name=PRIMARY_MODEL)
                            prompt = "Extract and transcribe all the text and questions from this image accurately."
                            active_img = st.session_state.captured_image if st.session_state.captured_image else Image.open(file_input)
                            resp = vault_model.generate_content([prompt, active_img])
                            extracted_text = resp.text
                            
                        # THE AGGRESSIVE DATABASE SAFETY LOCK
                        if len(extracted_text) > 35000:
                            extracted_text = extracted_text[:35000] + "\n\n[SYSTEM WARNING: Document reached the maximum database size. The end of the document was truncated.]"
                            
                        user_data["file_vault"] = extracted_text
                        save_current_student(username, user_data)
                        st.sidebar.success("Saved to Vault instantly! You can close the file now.")
                        st.rerun()
                    except Exception as e:
                        st.sidebar.error(f"Error saving to Vault: {e}")

        # ---------------------------------------------------------

        # --- SILENT AUTO-DOSSIER ENGINE ---
        if st.session_state.unsummarized_messages >= 14:
            with st.spinner("Christine is organizing her notes..."):
                try:
                    grab_count = st.session_state.unsummarized_messages
                    recent_chat = str(user_data["history"][-grab_count:]) 
                    
                    # UPDATED DOSSIER PROMPT TO TRACK FILE PROGRESS
                    memory_prompt = f"""
                    You are an expert teacher maintaining a highly compressed, long-term dossier on a student.
                    CURRENT DOSSIER: {user_data['summary']}
                    RECENT CHAT: {recent_chat}
                    TASK: Update the dossier to track their progress specifically for the topic: {selected_topic}.
                    CRITICAL RULES:
                    1. MASTERED TAGS: You MUST start the line with the exact topic tag [{selected_topic}] followed by "MASTERED: " (e.g., [{selected_topic}] MASTERED: specific concept).
                    2. GAP TAGS: You MUST start the line with the exact topic tag [{selected_topic}] followed by "GAP: " (e.g., [{selected_topic}] GAP: specific weakness).
                    3. PRUNE: If they master a previous GAP, delete that GAP tag. Keep the total summary under 150 words.
                    4. DOCUMENT PROGRESS: If they are working on a saved document, explicitly state which specific questions or paragraphs they have ALREADY finished so Christine doesn't repeat them tomorrow.
                    """
                    try:
                        analyzer = genai.GenerativeModel(model_name="gemini-1.5-flash-8b")
                        memory_response = analyzer.generate_content(memory_prompt)
                    except Exception:
                        analyzer = genai.GenerativeModel(model_name=FALLBACK_MODEL)
                        memory_response = analyzer.generate_content(memory_prompt)
                    
                    user_data["summary"] = memory_response.text.strip()
                    st.session_state.unsummarized_messages = 0
                    save_current_student(username, user_data)
                except Exception as e:
                    st.warning(f"Dossier update skipped. Error: {e}")

        # --- CHAT HISTORY ---
        for msg in user_data["history"]:
            role_display = "user" if msg["role"] == "user" else "assistant"
            with st.chat_message(role_display):
                st.markdown(msg["content"])

        # --- INPUT & PROCESSING ---
        st.markdown("""
            <style>
            [data-testid="stAudioInput"] { position: fixed; bottom: 85px; z-index: 999; }
            .block-container { padding-bottom: 150px !important; }
            </style>
            """, unsafe_allow_html=True)

        user_audio = st.audio_input("🎤 Talk to Christine")
        user_text = st.chat_input("...or type your question here")

        active_image = None
        is_new_image = False
        
        if st.session_state.captured_image:
            active_image = st.session_state.captured_image
            file_id = f"cam-{str(active_image.size)}"
        elif file_input:
            active_image = file_input
            file_id = f"file-{file_input.name}-{file_input.size}"
        else:
            file_id = None

        if file_id and file_id != st.session_state.last_processed_file_id:
            is_new_image = True

        is_new_audio = False
        audio_id = None
        if user_audio:
            audio_id = f"audio-{user_audio.size}"
            if audio_id != st.session_state.last_processed_audio_id:
                is_new_audio = True

        auto_topic = st.session_state.pop("auto_submit_topic", None)
        
        has_text = bool(user_text)
        has_image = bool(is_new_image and active_image)
        has_audio = bool(is_new_audio and user_audio)
        
        if has_text or has_image or has_audio or auto_topic:
            
            display_text = user_text if user_text else ""
            current_turn_content = []
            
            if auto_topic:
                display_text = f"I am switching topics to **{auto_topic}**. Please check my dossier and test me on the next concept I need to learn."
                current_turn_content.append(display_text)
                
            if has_text: 
                current_turn_content.append(user_text)

            if has_audio:
                audio_part = {"mime_type": "audio/wav", "data": user_audio.getvalue()}
                current_turn_content.append(audio_part)
                display_text += "\n\n[🎤 Voice Message]"
                st.session_state.last_processed_audio_id = audio_id
            
            pil_image = None
            pdf_part = None
            if has_image:
                try:
                    if not isinstance(active_image, Image.Image) and active_image.name.lower().endswith('.pdf'):
                        pdf_part = {"mime_type": "application/pdf", "data": active_image.getvalue()}
                        current_turn_content.append(pdf_part)
                    else:
                        pil_image = active_image if isinstance(active_image, Image.Image) else Image.open(active_image)
                        current_turn_content.append(pil_image)
                    
                    if image_action == "Review my work for mistakes":
                        action_prompt = "SYSTEM OVERRIDE: Please review my attached work. Tell me what I did right and help me correct any mistakes one step at a time."
                    elif image_action == "Quiz me on this content":
                        action_prompt = "SYSTEM OVERRIDE: Please analyze this attached content. Do not ask if I am ready. IMMEDIATELY ask me the very first diagnostic quiz question strictly based on this material to test my understanding."
                    else:
                        action_prompt = "SYSTEM OVERRIDE: Please analyze the attached English/Literature material. Guide me through it step-by-step to improve my vocabulary, grammar, and cognitive understanding of the text. Do not give me the answers. Ask me one thought-provoking question at a time about literary devices, connotations, or characterisation based on this specific text."
                        
                    file_label = "📄 Attached PDF" if pdf_part else "📸 Attached Image"
                    display_text += f"\n\n[{file_label}: {action_prompt}]"
                    st.session_state.last_processed_file_id = file_id
                except Exception as e:
                    st.error(f"Error processing file: {e}")
                    
            with st.chat_message("user"):
                if auto_topic: st.markdown(f"*(Switched topic to {auto_topic})*")
                if has_text: st.markdown(user_text)
                if has_image:
                    if pil_image:
                        st.image(pil_image, caption="Work for Review")
                    elif pdf_part:
                        st.markdown(f"📄 **PDF Document Uploaded:** `{active_image.name}`")
                if has_audio: st.audio(user_audio) 
            
            user_data["history"].append({"role": "user", "content": display_text})

            # --- AI GENERATION ---
            try:
                # INJECTING THE VAULT DATA INTO CHRISTINE'S BRAIN
                system_instruction = get_system_instruction(user_data["age"], current_subject, user_data["summary"], user_data.get("file_vault", ""))
                
                chat_history = convert_history_for_gemini([msg for msg in user_data["history"][:-1] if msg.get("content")])
                
                if chat_history and chat_history[0]["role"] != "user":
                    chat_history.insert(0, {"role": "user", "parts": ["Hello"]})

                with st.chat_message("assistant"):
                    with st.spinner("Christine is analyzing..."):
                        try:
                            model = genai.GenerativeModel(
                                model_name=PRIMARY_MODEL, 
                                system_instruction=system_instruction
                            )
                            if has_image or has_audio:
                                prompt_parts = [system_instruction] + [msg['parts'][0] for msg in chat_history] + current_turn_content
                                response = model.generate_content(prompt_parts)
                            else:
                                chat = model.start_chat(history=chat_history)
                                response = chat.send_message(display_text)
                        except Exception:
                            model = genai.GenerativeModel(
                                model_name=FALLBACK_MODEL, 
                                system_instruction=system_instruction
                            )
                            if has_image or has_audio:
                                prompt_parts = [system_instruction] + [msg['parts'][0] for msg in chat_history] + current_turn_content
                                response = model.generate_content(prompt_parts)
                            else:
                                chat = model.start_chat(history=chat_history)
                                response = chat.send_message(display_text)
                    
                        answer = response.text.replace("🎤 Voice Response", "").replace("🎤 Voice response", "").replace("🎤 Voice Message", "").replace("🎤 [Voice Message]", "").replace("*[🎤 Voice Message]*", "").strip()
                        
                        if not answer:
                            answer = "I'm sorry, I had trouble processing that. Could you try asking again?"
                            
                        st.markdown(answer)
                        
                        if voice_on:
                            try:
                                clean_speech = answer.replace('**', '').replace('#', '').replace('`', '').replace('_', '')
                                clean_speech = re.sub(r'^\s*[\*\-]\s+', ' ', clean_speech, flags=re.MULTILINE)
                                clean_speech = re.sub(r'\s+', ' ', clean_speech).strip()
                                
                                sound_file = io.BytesIO()
                                tts = gTTS(text=clean_speech, lang='en', tld='co.uk')
                                tts.write_to_fp(sound_file)
                                sound_file.seek(0)
                                
                                st.audio(sound_file, format='audio/mpeg', autoplay=True)
                            except Exception as e:
                                st.error(f"Audio generation skipped: {e}")
                
                        if st.session_state.captured_image:
                            st.session_state.captured_image = None
                
                user_data["history"].append({"role": "model", "content": answer})
                save_current_student(username, user_data)
                st.session_state.unsummarized_messages += 2

            except Exception as e:
                 st.error(f"Connection Error: {e}")

elif not api_key:
     st.warning("Please configure your API Key.")
