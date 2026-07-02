import pandas as pd
import datetime
import os
import re
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright

# ==========================================
# 準備：今日の日付と道具の設定
# ==========================================
today_dt = datetime.date.today() - datetime.timedelta(days=1)
today = today_dt.strftime('%Y-%m-%d')
print(f"{today} 分のデータとして記録を開始します（実行日: {datetime.date.today().strftime('%Y-%m-%d')}）")

projects_file = 'projects.csv'
daily_file = 'daily_logs.csv'
scraped_new_projects = []
today_logs = []

# Playwright（高機能な仮想ブラウザ）を起動
with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page()

    # ==========================================
    # 第1部：名簿（projects.csv）の更新
    # ==========================================
    print("新着ページから新しいプロジェクトを探しています...")
    for page_num in range(1, 6):
        url = f"https://camp-fire.jp/projects/search?sort=new&page={page_num}"
        try:
            # 【修正点】完全に静かになるのを待たず、基本の枠組みが読み込めたらOKとする
            page.goto(url, wait_until="domcontentloaded", timeout=20000)
            # JavaScriptが中身を描画するのを3秒だけ待つ
            page.wait_for_timeout(3000)
            
            html = page.content()
            soup = BeautifulSoup(html, 'html.parser')
            
            cards = soup.select('.project-box') or soup.select('.project-card') or soup.select('[class*="project-card"]')
            
            if page_num == 1 and not cards:
                print("【警告】ブラウザを使ってもカードが見つかりません。")
                
            for card in cards:
                title_tag = card.select_one('.project-title') or card.select_one('[class*="title"]')
                title = title_tag.text.strip() if title_tag else "タイトル不明"
                
                link = ""
                if title_tag and title_tag.find('a'):
                    link = title_tag.find('a')['href']
                else:
                    a_tag = card.find('a')
                    link = a_tag['href'] if a_tag else ""
                    
                if link and not link.startswith('http'):
                    link = "https://camp-fire.jp" + link
                    
                days_str = card.select_one('.remain_days') or card.select_one('[class*="remain"]')
                days_text = days_str.text if days_str else "0"
                days_left = int(re.sub(r'\D', '', days_text)) if re.sub(r'\D', '', days_text) else 0
                
                end_date = (today_dt + datetime.timedelta(days=days_left)).strftime('%Y-%m-%d')
                    
                if link:
                    scraped_new_projects.append({
                        'project_url': link, 
                        'title': title,
                        'end_date': end_date
                    })
        except Exception as e:
            print(f"{page_num}ページの取得中にエラー: {e}")

    # 名簿の保存処理
    if scraped_new_projects:
        df_scraped_projects = pd.DataFrame(scraped_new_projects).drop_duplicates(subset=['project_url'])
    else:
        df_scraped_projects = pd.DataFrame(columns=['project_url', 'title', 'end_date'])

    if os.path.exists(projects_file):
        df_existing_projects = pd.read_csv(projects_file)
        if not df_existing_projects.empty or not df_scraped_projects.empty:
            df_all_projects = pd.concat([df_existing_projects, df_scraped_projects]).drop_duplicates(subset=['project_url'], keep='first')
        else:
            df_all_projects = df_existing_projects
    else:
        df_all_projects = df_scraped_projects

    df_all_projects.to_csv(projects_file, index=False)
    print(f"名簿の更新完了。現在 {len(df_all_projects)} 件のプロジェクトが登録されています。")

    # ==========================================
    # 第2部：日々の記録（daily_logs.csv）の取得
    # ==========================================
    if not df_all_projects.empty:
        print("名簿に載っているプロジェクトの今日の数字を確認します...")
        for index, row in df_all_projects.iterrows():
            url = row['project_url']
            end_date_str = str(row['end_date'])
            
            if end_date_str < today:
                continue
                
            try:
                # 【修正点】ここも同様に修正
                page.goto(url, wait_until="domcontentloaded", timeout=20000)
                page.wait_for_timeout(2000)
                
                html = page.content()
                soup = BeautifulSoup(html, 'html.parser')
                
                amount_str = soup.select_one('.total-amount') or soup.select_one('[class*="amount"]')
                amount_text = amount_str.text if amount_str else "0"
                amount = int(re.sub(r'\D', '', amount_text)) if re.sub(r'\D', '', amount_text) else 0
                
                supporters_str = soup.select_one('.supporters') or soup.select_one('[class*="supporter"]')
                supporters_text = supporters_str.text if supporters_str else "0"
                supporters = int(re.sub(r'\D', '', supporters_text)) if re.sub(r'\D', '', supporters_text) else 0
                
                days_str = soup.select_one('.remain_days') or soup.select_one('[class*="remain"]')
                days_text = days_str.text if days_str else "0"
                days_left = int(re.sub(r'\D', '', days_text)) if re.sub(r'\D', '', days_text) else 0
                
                today_logs.append({
                    'date': today,
                    'project_url': url,
                    'current_amount': amount,
                    'supporters': supporters,
                    'days_left': days_left
                })
            except Exception as e:
                print(f"{url} の取得でエラーが発生しました。スキップします。")

    browser.close()

# ==========================================
# 第3部：前日との比較と保存
# ==========================================
if today_logs:
    print("昨日のデータと比較して、1日あたりの数字を計算します...")
    df_today = pd.DataFrame(today_logs)
    
    if os.path.exists(daily_file):
        df_past = pd.read_csv(daily_file)
        if not df_past.empty:
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
            df_final = df_merged[['date', 'project_url', 'current_amount', 'supporters', 'days_left', 'daily_amount', 'daily_supporters', 'daily_average_amount']]
        else:
            df_today['daily_amount'] = 0
            df_today['daily_supporters'] = 0
            df_today['daily_average_amount'] = 0
            df_final = df_today[['date', 'project_url', 'current_amount', 'supporters', 'days_left', 'daily_amount', 'daily_supporters', 'daily_average_amount']]
    else:
        df_today['daily_amount'] = 0
        df_today['daily_supporters'] = 0
        df_today['daily_average_amount'] = 0
        df_final = df_today[['date', 'project_url', 'current_amount', 'supporters', 'days_left', 'daily_amount', 'daily_supporters', 'daily_average_amount']]

    if not os.path.exists(daily_file):
        df_final.to_csv(daily_file, mode='w', header=True, index=False)
    else:
        df_final.to_csv(daily_file, mode='a', header=False, index=False)
    print("すべての作業が完了しました！")
else:
    print("【警告】本日は有効なプロジェクトデータが1件も取得できなかったため、処理を安全にスキップしました。")
