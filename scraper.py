import pandas as pd
import datetime
import os
import re
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright

# ==========================================
# 準備：今日の日付と道具の設定
# ==========================================
# 夜中に動くため、日付を1日巻き戻して「昨日分」として記録する
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
            page.goto(url, wait_until="domcontentloaded", timeout=20000)
            page.wait_for_timeout(3000) # 描画を3秒待つ
            
            html = page.content()
            soup = BeautifulSoup(html, 'html.parser')
            
            # 【新目印】Svelte対応の新しいカードの箱を探す
            cards = soup.select('li.card-wrapper') or soup.select('.card') or soup.select('[class*="card-wrapper"]')
            
            for card in cards:
                # 【新目印】タイトルの取得
                title_tag = card.select_one('h2.name') or card.select_one('[class*="name"]')
                title = title_tag.text.strip() if title_tag else "タイトル不明"
                
                # 【新目岩】URLの取得と整形
                a_tag = card.select_one('a.card') or card.find('a')
                raw_link = a_tag['href'] if a_tag and a_tag.has_attr('href') else ""
                
                if raw_link:
                    # URLからプロジェクトID（数字）を抜き出して綺麗なURLに統一する
                    match = re.search(r'/projects/(\d+)', raw_link)
                    if match:
                        link = f"https://camp-fire.jp/projects/{match.group(1)}"
                    else:
                        continue
                else:
                    continue
                    
                # 【新目印】残り日数の取得
                days_str = card.select_one('.footer-item.per') or card.select_one('[class*="per"]')
                days_text = days_str.text if days_str else "0"
                days_left = int(re.sub(r'\D', '', days_text)) if re.sub(r'\D', '', days_text) else 0
                
                end_date = (today_dt + datetime.timedelta(days=days_left)).strftime('%Y-%m-%d')
                    
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
                page.goto(url, wait_until="domcontentloaded", timeout=20000)
                page.wait_for_timeout(2000)
                
                html = page.content()
                soup = BeautifulSoup(html, 'html.parser')
                
                # --- 金額の取得（クラス名 ＋ 文字列探知のハイブリッド） ---
                amount = 0
                amount_element = soup.select_one('.footer-item.total') or soup.select_one('.total-amount') or soup.select_one('[class*="total"]') or soup.select_one('[class*="amount"]')
                if amount_element:
                    amount = int(re.sub(r'\D', '', amount_element.text)) if re.sub(r'\D', '', amount_element.text) else 0
                if amount == 0: # バックアップ：画面上の「現在」という文字の親要素から数字を抜く
                    for target in soup.find_all(text=re.compile(r'現在')):
                        digits = re.sub(r'\D', '', target.parent.text)
                        if digits: amount = int(digits); break
                
                # --- 支援者の取得（クラス名 ＋ 文字列探知のハイブリッド） ---
                supporters = 0
                supporters_element = soup.select_one('.footer-item.rest') or soup.select_one('.supporters') or soup.select_one('[class*="rest"]') or soup.select_one('[class*="supporter"]')
                if supporters_element:
                    supporters = int(re.sub(r'\D', '', supporters_element.text)) if re.sub(r'\D', '', supporters_element.text) else 0
                if supporters == 0: # バックアップ：画面上の「支援者」という文字から数字を抜く
                    for target in soup.find_all(text=re.compile(r'支援者')):
                        digits = re.sub(r'\D', '', target.parent.text)
                        if digits: supporters = int(digits); break
                
                # --- 残り日数の取得 ---
                days_left = 0
                days_element = soup.select_one('.footer-item.per') or soup.select_one('.remain_days') or soup.select_one('[class*="per"]') or soup.select_one('[class*="remain"]')
                if days_element:
                    days_left = int(re.sub(r'\D', '', days_element.text)) if re.sub(r'\D', '', days_element.text) else 0
                if days_left == 0: # バックアップ：画面上の「残り」という文字から数字を抜く
                    for target in soup.find_all(text=re.compile(r'残り')):
                        digits = re.sub(r'\D', '', target.parent.text)
                        if digits: days_left = int(digits); break
                
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
