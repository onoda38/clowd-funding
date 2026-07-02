import requests
from bs4 import BeautifulSoup
import pandas as pd
import datetime
import os
import time
import re

# ==========================================
# 準備：今日の日付と道具の設定
# ==========================================
today_dt = datetime.date.today()
today = today_dt.strftime('%Y-%m-%d')
print(f"{today} のデータ取得を開始します！")

headers = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
}

# ==========================================
# 第1部：名簿（projects.csv）の更新
# ==========================================
projects_file = 'projects.csv'
scraped_new_projects = []

print("新着ページから新しいプロジェクトを探しています...")
for page in range(1, 6):
    url = f"https://camp-fire.jp/projects/search?sort=new&page={page}"
    res = requests.get(url, headers=headers)
    soup = BeautifulSoup(res.text, 'html.parser')
    
    cards = soup.select('.project-box')
    for card in cards:
        title_tag = card.select_one('.project-title')
        title = title_tag.text.strip() if title_tag else "タイトル不明"
        link = title_tag.find('a')['href'] if title_tag and title_tag.find('a') else ""
        if link and not link.startswith('http'):
            link = "https://camp-fire.jp" + link
            
        # 【重要】残り日数を取得して、終了予定日を計算する
        days_str = card.select_one('.remain_days').text if card.select_one('.remain_days') else "0"
        days_left = int(re.sub(r'\D', '', days_str))
        
        # 終了予定日 ＝ 今日 ＋ 残り日数
        end_date = (today_dt + datetime.timedelta(days=days_left)).strftime('%Y-%m-%d')
            
        if link:
            scraped_new_projects.append({
                'project_url': link, 
                'title': title,
                'end_date': end_date  # 名簿に終了日をメモしておく
            })
            
    time.sleep(2)

# 新しく見つけたものを表にする
df_scraped_projects = pd.DataFrame(scraped_new_projects).drop_duplicates(subset=['project_url'])

# 過去の名簿（projects.csv）があれば合体させ、古い終了日の記録を優先して残す
if os.path.exists(projects_file):
    df_existing_projects = pd.read_csv(projects_file)
    df_all_projects = pd.concat([df_existing_projects, df_scraped_projects]).drop_duplicates(subset=['project_url'], keep='first')
else:
    df_all_projects = df_scraped_projects

# 名簿を上書き保存する
df_all_projects.to_csv(projects_file, index=False)
print(f"名簿の更新完了。現在 {len(df_all_projects)} 件のプロジェクトが登録されています。")

# ==========================================
# 第2部：日々の記録（daily_logs.csv）の取得
# ==========================================
daily_file = 'daily_logs.csv'
today_logs = []

print("名簿に載っているプロジェクトの今日の数字を確認します...")
for index, row in df_all_projects.iterrows():
    url = row['project_url']
    end_date_str = str(row['end_date'])
    
    # 【自動終了ブレーキ】終了予定日が今日より前（過去）なら、アクセスせずにスキップ！
    if end_date_str < today:
        continue
        
    try:
        res = requests.get(url, headers=headers)
        soup = BeautifulSoup(res.text, 'html.parser')
        
        amount_str = soup.select_one('.total-amount').text if soup.select_one('.total-amount') else "0"
        amount = int(re.sub(r'\D', '', amount_str))
        
        supporters_str = soup.select_one('.supporters').text if soup.select_one('.supporters') else "0"
        supporters = int(re.sub(r'\D', '', supporters_str))
        
        # 締切までの残り日数もデータ分析用に記録しておく
        days_str = soup.select_one('.remain_days').text if soup.select_one('.remain_days') else "0"
        days_left = int(re.sub(r'\D', '', days_str))
        
        today_logs.append({
            'date': today,
            'project_url': url,
            'current_amount': amount,
            'supporters': supporters,
            'days_left': days_left
        })
    except Exception as e:
        print(f"{url} の取得でエラーが発生しました。スキップします。")
        
    time.sleep(2) # 2秒待つ

df_today = pd.DataFrame(today_logs)

# ==========================================
# 第3部：前日との比較（引き算と割り算）と保存
# ==========================================
print("昨日のデータと比較して、1日あたりの数字を計算します...")
if os.path.exists(daily_file) and not df_today.empty:
    df_past = pd.read_csv(daily_file)
    df_past_latest = df_past.sort_values('date').drop_duplicates(subset=['project_url'], keep='last')
    
    df_merged = pd.merge(df_today, df_past_latest[['project_url', 'current_amount', 'supporters']], 
                         on='project_url', how='left', suffixes=('', '_past'))
    
    df_merged['current_amount_past'] = df_merged['current_amount_past'].fillna(df_merged['current_amount'])
    df_merged['supporters_past'] = df_merged['supporters_past'].fillna(df_merged['supporters'])
    
    df_merged['daily_amount'] = df_merged['current_amount'] - df_merged['current_amount_past']
    df_merged['daily_supporters'] = df_merged['supporters'] - df_merged['supporters_past']
    
    df_merged['daily_average_amount'] = df_merged.apply(
        lambda row: int(row['daily_amount'] / row['daily_supporters']) if row['daily_supporters'] > 0 else 0,
        axis=1
    )
    
    # 保存する項目の順番を整理
    df_final = df_merged[['date', 'project_url', 'current_amount', 'supporters', 'days_left', 'daily_amount', 'daily_supporters', 'daily_average_amount']]
else:
    # 初回実行の場合
    df_today['daily_amount'] = 0
    df_today['daily_supporters'] = 0
    df_today['daily_average_amount'] = 0
    df_final = df_today[['date', 'project_url', 'current_amount', 'supporters', 'days_left', 'daily_amount', 'daily_supporters', 'daily_average_amount']]

# 日々の記録ノート（daily_logs.csv）に書き足す
if not os.path.exists(daily_file):
    df_final.to_csv(daily_file, mode='w', header=True, index=False)
else:
    df_final.to_csv(daily_file, mode='a', header=False, index=False)

print("すべての作業が完了しました！")
