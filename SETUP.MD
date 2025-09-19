🚀 How to Set Up and Run Your Upgraded Crypto Bot
Your bot is now a full web application with PIN protection, history, and a new UI.

Part 1: Initial Setup
Update Python Libraries: Your requirements.txt file is the same, but it's good practice to re-run the install command to ensure everything is up to date.

Navigate to your crypto-bot folder in the terminal.

Run: pip install -r requirements.txt (or python3 -m pip install ...)

Set Up Your PIN:

Open the .env file.

Find the line BOT_PIN="1234" and change "1234" to your own secret 4-digit PIN. Save the file.

Part 2: Running the Bot and Admin Panel
Run the Server: In your terminal (inside the crypto-bot folder), start the server with this full command:

python3 -m uvicorn main:app --reload

Access the Admin Panel:

Open your web browser and go directly to this address: https://www.google.com/search?q=http://127.0.0.1:8000

You will be greeted with a PIN entry screen. Enter the 4-digit PIN you set in your .env file to unlock the main dashboard.

New Files Created:

When you first run the bot and change settings or when signals are found, two new files will be created in your folder:

config.json: Stores your bot's settings.

trade_history.json: Stores the log of all signals found.

You can safely ignore these files, but don't delete them, as they give your bot its memory!

# To run: python3 -m uvicorn main:app --reload
