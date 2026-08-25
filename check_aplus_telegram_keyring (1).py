import keyring
s="CAlphaTrader:Telegram"
a=bool(keyring.get_password(s,"bot_token")); b=bool(keyring.get_password(s,"chat_id"))
print("PASS: Existing CAlphaTrader Telegram credentials found." if a and b else "FAIL: Telegram credentials not found.")
print("Service:",s)
print("Credential values: NOT DISPLAYED")
