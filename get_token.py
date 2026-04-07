"""
第一次執行這個腳本取得 Yahoo OAuth Refresh Token
之後只需要把 refresh_token 存到 GitHub Secrets 就好

使用方式：
  pip install requests
  python get_token.py
"""

import requests
import urllib.parse
import webbrowser

CLIENT_ID     = input("請輸入你的 Yahoo Client ID: ").strip()
CLIENT_SECRET = input("請輸入你的 Yahoo Client Secret: ").strip()

REDIRECT_URI  = "oob"  # Out-of-Band，不需要 web server
SCOPE         = "fspt-r"  # Fantasy Sports read

# Step 1: 產生授權 URL
auth_url = (
    "https://api.login.yahoo.com/oauth2/request_auth"
    f"?client_id={CLIENT_ID}"
    f"&redirect_uri={REDIRECT_URI}"
    f"&response_type=code"
    f"&scope={SCOPE}"
    f"&language=en-us"
)

print("\n請在瀏覽器中開啟以下連結並授權：")
print(auth_url)
webbrowser.open(auth_url)

code = input("\n授權完成後，把頁面上的 code 貼到這裡: ").strip()

# Step 2: 用 code 換 tokens
resp = requests.post(
    "https://api.login.yahoo.com/oauth2/get_token",
    data={
        "grant_type":   "authorization_code",
        "code":          code,
        "redirect_uri":  REDIRECT_URI,
    },
    auth=(CLIENT_ID, CLIENT_SECRET),
    headers={"Content-Type": "application/x-www-form-urlencoded"},
)

if resp.status_code != 200:
    print(f"\n❌ 錯誤: {resp.text}")
else:
    data = resp.json()
    print("\n✅ 成功取得 Token！")
    print(f"\nAccess Token (短期，不用存):\n{data['access_token'][:40]}...")
    print(f"\nRefresh Token (這個存到 GitHub Secrets!):\n{data['refresh_token']}")
    print(f"\n請把以下資訊存到 GitHub Secrets：")
    print(f"  YAHOO_CLIENT_ID      = {CLIENT_ID}")
    print(f"  YAHOO_CLIENT_SECRET  = {CLIENT_SECRET}")
    print(f"  YAHOO_REFRESH_TOKEN  = {data['refresh_token']}")

    # 找你的 League ID
    print("\n\n現在幫你查詢你的 League ID...")
    headers = {"Authorization": f"Bearer {data['access_token']}"}
    leagues_resp = requests.get(
        "https://fantasysports.yahooapis.com/fantasy/v2/users;use_login=1/games;game_codes=mlb/leagues?format=json",
        headers=headers
    )
    if leagues_resp.status_code == 200:
        try:
            ldata = leagues_resp.json()
            games = ldata["fantasy_content"]["users"]["0"]["user"][1]["games"]
            count = games["count"]
            for i in range(count):
                game = games[str(i)]["game"]
                leagues = game[1].get("leagues", {})
                lcount = leagues.get("count", 0)
                for j in range(lcount):
                    l = leagues[str(j)]["league"][0]
                    print(f"\n找到 League: {l['name']}")
                    print(f"  YAHOO_LEAGUE_ID = {l['league_key']}")
        except Exception as e:
            print(f"解析 League 資訊時出錯: {e}")
            print("請手動在 Yahoo Fantasy 網站查詢你的 League ID")
    else:
        print("查詢 League 失敗，請手動在 Yahoo Fantasy 網站查詢")
