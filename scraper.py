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

def safe_extract_num(text):
    if not text: return 0
    text = str(text).strip()[:100]
    match = re.search(r'([0-9]{1,3}(?:,[0-9]{3})*|[0-9]+)', text)
    if match:
        try:
            return int(match.group(1).replace(',', ''))
        except:
            return 0
    return 0

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
            page.goto(url, wait_until="domcontentloaded", timeout=20000)
            page.wait_for_timeout(3000)
            
            html = page.content()
            soup = BeautifulSoup(html, 'html.parser')
            
            cards = soup.select('li.card-wrapper') or soup.select('.card') or soup.select('[class*="card-wrapper"]')
            
            for card in cards:
                title_tag = card.select_one('h2.name') or card.select_one('[class*="name"]')
                title = title_tag.text.strip() if title_tag else "タイトル不明"
                
                a_tag = card.select_one('a.card') or card.find('a')
                raw_link = a_tag['href'] if a_tag and a_tag.has_attr('href') else ""
                
                if raw_link:
                    match = re.search(r'/projects/(\d+)', raw_link)
                    if match:
                        link = f"https://camp-fire.jp/projects/{match.group(1)}"
                    else:
                        continue
                else:
                    continue
                    
                # 一覧ページでの残り日数
                days_str = card.select_one('.footer-item.per') or card.select_one('[class*="per"]')
                days_text = days_str.text if days_str else "0"
                days_left = safe_extract_num(days_text)
                
                end_date = (today_dt + datetime.timedelta(days=days_left)).strftime('%Y-%m-%d')
                    
                scraped_new_projects.append({
                    'project_url': link, 
                    'title': title,
                    'end_date': end_date
                })
        except Exception as e:
            print(f"{page_num}ページの取得中にエラー: {e}")

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
                page.goto(url, wait_until="domcontentloaded", timeout=20000)
                page.wait_for_timeout(2000)
                
                html = page.content()
                soup = BeautifulSoup(html, 'html.parser')
                
                # ① 現在の支援額（.backer-amount を最優先）
                amount = 0
                amount_element = soup.select_one('.backer-amount') or soup.select_one('.footer-item.total') or soup.select_one('.total-amount')
                if amount_element:
                    amount = safe_extract_num(amount_element.text)
                
                # ②【新機能】目標金額（.target-amount を最優先）
                target_amount = 0
                target_element = soup.select_one('.target-amount')
                if target_element:
                    target_amount = safe_extract_num(target_element.text)
                
                # ③【新機能】達成率（.percentage を最優先）
                achievement_rate = 0
                rate_element = soup.select_one('.percentage')
                if rate_element:
                    # 「217%」から数字の「217」だけを安全に抜き取る
                    achievement_rate = safe_extract_num(rate_element.text)
                
                # ④ 支援者数
                supporters = 0
                supporters_element = soup.select_one('.backers') or soup.select_one('.backer-count') or soup.select_one('.footer-item.rest')
                if supporters_element:
                    supporters = safe_extract_num(supporters_element.text)
                
                # ⑤ 残り日数（.days-left を最優先にアップデート）
                days_left = 0
                days_element = soup.select_one('.days-left') or soup.select_one('.time-remaining') or soup.select_one('.footer-item.per')
                if days_element:
                    days_left = safe_extract_num(days_element.text)
                
                today_logs.append({
                    'date': today,
                    'project_url': url,
                    'current_amount': amount,
                    'target_amount': target_amount,
                    'achievement_rate': achievement_rate,
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
    
    # 新しく追加した列を含めた綺麗な並び順を定義
    columns_order = [
        'date', 'project_url', 'current_amount', 'target_amount', 'achievement_rate', 
        'supporters', 'days_left', 'daily_amount', 'daily_supporters', 'daily_average_amount'
    ]
    
    if os.path.exists(daily_file):
        df_past = pd.read_csv(daily_file)
        if not df_past.empty:
            df_past_latest = df_past.sort_values('date').drop_duplicates(subset=['project_url'], keep='last')
            
            # 過去データとドッキング
            df_merged = pd.merge(df_today, df_past_latest[['project_url', 'current_amount', 'supporters']], 
                                 on='project_url', how='left', suffixes=('', '_past'))
            
            df_merged['current_amount_past'] = df_merged['current_amount_past'].fillna(df_merged['current_amount'])
            df_merged['supporters_past'] = df_merged['supporters_past'].fillna(df_merged['supporters'])
            
            # 日次差分の計算
            df_merged['daily_amount'] = df_merged['current_amount'] - df_merged['current_amount_past']
            df_merged['daily_supporters'] = df_merged['supporters'] - df_merged['supporters_past']
            df_merged['daily_average_amount'] = df_merged.apply(
                lambda row: int(row['daily_amount'] / row['daily_supporters']) if row['daily_supporters'] > 0 else 0,
                axis=1
            )
            df_final = df_merged[columns_order]
        else:
            for col in ['daily_amount', 'daily_supporters', 'daily_average_amount']:
                df_today[col] = 0
            df_final = df_today[columns_order]
    else:
        for col in ['daily_amount', 'daily_supporters', 'daily_average_amount']:
            df_today[col] = 0
        df_final = df_today[columns_order]

    # CSVへの保存（上書きまたは追記）
    if not os.path.exists(daily_file):
        df_final.to_csv(daily_file, mode='w', header=True, index=False)
    else:
        # すでにファイルがある場合は、古い見出し行を壊さないように、データ行だけを追記する
        df_final.to_csv(daily_file, mode='a', header=False, index=False)
    print("すべての作業が完了しました！")
else:
    print("【警告】本日は有効なプロジェクトデータが1件も取得できなかったため、処理を安全にスキップしました。")
