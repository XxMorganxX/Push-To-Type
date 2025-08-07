# Push-to-Type (Auto Prompter)

Hold a key combo, speak, release – your speech is typed for you.

Uses AssemblyAI impressively cheap, fast, and free model for transcription.
https://www.assemblyai.com/docs/api-reference/streaming-api/streaming-api

## Quick Setup

```bash
# 1. clone / download the project
cd /path/to/Auto-Prompter

# 2. create & activate a virtual env (optional)
python3.13 -m venv venv && source venv/bin/activate

# 3. Ensure portAudio package is installed
brew install portaudio

# 3. install deps
pip install -r requirements.txt  # or: pip install assemblyai python-dotenv pynput pyautogui psutil

#4. Find API key by going to this link and hitting sign up (Free)
https://www.assemblyai.com/docs/api-reference/streaming-api/streaming-api

# 5. add your AssemblyAI key
change files nmae ".env.example" to ".env" and replace with AssemblyAI API KEY

# 6. run it in background terminal
./autoprompt          # easiest (has its own launcher)
# or
python src/main.py    # same program

# 7. Open preference (on mac) to give terminal access
open "x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility"
```

Default shortcut: **Left-Shift + Right-Shift**

• Hold both shifts = start recording
• Release = text appears wherever the cursor is

Change shortcuts in `config.py`.

That’s it – push, talk, type.
