import fitz
import requests
import json
import os
import sys
import tempfile
from urllib.parse import urlparse, unquote
from pathlib import Path
from typing import List, Dict, Optional

class PDF2MDConverter:
    def __init__(self):
        self.gyazo_token = os.getenv('GYAZO_TOKEN')
        self.openai_api_key = os.getenv('OPENAI_API_KEY')
        
        if not self.gyazo_token:
            raise ValueError("GYAZO_TOKEN環境変数が設定されていません")
        if not self.openai_api_key:
            raise ValueError("OPENAI_API_KEY環境変数が設定されていません")

    def upload_image_to_gyazo(self, image_bytes: bytes) -> Optional[str]:
        url = "https://upload.gyazo.com/api/upload"
        files = {'imagedata': image_bytes}
        data = {'access_token': self.gyazo_token}
        
        try:
            response = requests.post(url, files=files, data=data)
            if response.status_code == 200:
                result = response.json()
                return result.get('url')
            else:
                print(f"Gyazoアップロード失敗: {response.status_code}")
                return None
        except Exception as e:
            print(f"Gyazoアップロードエラー: {e}")
            return None

    def extract_pdf_content(self, pdf_path: str) -> List[Dict]:
        document = fitz.open(pdf_path)
        pages_data = []
        
        for page_num in range(len(document)):
            page = document.load_page(page_num)
            
            text = page.get_text("text")
            image_urls = []
            
            image_list = page.get_images(full=True)
            if image_list.__len__() < 15:
                for img_index, img in enumerate(image_list):
                    xref = img[0]
                    base_image = document.extract_image(xref)
                    image_bytes = base_image["image"]
                    
                    gyazo_url = self.upload_image_to_gyazo(image_bytes)
                    if gyazo_url:
                        image_urls.append(gyazo_url)
                        print(f"ページ {page_num + 1} の画像 {img_index + 1} をGyazoにアップロード: {gyazo_url}")
            
            page_data = {
                'page_number': page_num + 1,
                'text': text.strip(),
                'images': image_urls
            }
            pages_data.append(page_data)
            print(f"ページ {page_num + 1} を処理完了")
        
        document.close()
        return pages_data

    def generate_markdown_summary(self, pages_data: List[Dict]) -> str:
        content_description = []
        for page in pages_data:
            page_desc = f"ページ{page['page_number']}には以下のテキストがあります：\n{page['text'][:500]}..."
            if page['images']:
                page_desc += f"\nまた、{len(page['images'])}個の画像があります："
                for i, img_url in enumerate(page['images']):
                    page_desc += f"\n画像{i+1}: {img_url}"
            content_description.append(page_desc)
        
        prompt = f"""以下のPDFの各ページの内容を日本語で包括的に要約し、適切なMarkdown形式で出力してください。
画像がある場合は、その画像へのリンクを適切に配置してください。

{chr(10).join(content_description)}

要求：
1. 日本語での包括的な内容要約
2. 適切なMarkdown形式（見出し、リスト、画像リンクなど）
3. 画像は ![画像の説明](画像URL) の形式で挿入
  - 存在しない画像を創造、予測してはいけません、提供されたデータに基づいてください。提供されたデータに画像が含まれない場合、画像リンクは挿入しないでください。
4. 論理的な構造で整理された内容
5. 数値的なデータが含まれる場合は適切にテーブルで表現

もとのデータはページごとに分かれていますが、これは全体の論理構成とは一致しないはずですから、〜ページには以下の内容がある、という形でまとめてはいけません。あくまで与えられたデータから論理構成を再構築し、適切に画像リンクを配置しつつMarkdownにしてください。

Markdownそれだけを出力してください。余計なものは出力しないでください。
"""

        headers = {
            'Authorization': f'Bearer {self.openai_api_key}',
            'Content-Type': 'application/json'
        }
        
        data = {
            'model': 'gpt-5-mini',
            'messages': [
                {'role': 'user', 'content': prompt}
            ],
        }
        
        try:
            response = requests.post(
                'https://api.openai.com/v1/chat/completions',
                headers=headers,
                json=data
            )
            
            if response.status_code == 200:
                result = response.json()
                return result['choices'][0]['message']['content']
            else:
                print(f"OpenAI API エラー: {response.status_code}")
                return f"API呼び出しに失敗しました: {response.text}"
        except Exception as e:
            print(f"OpenAI API呼び出しエラー: {e}")
            return f"エラーが発生しました: {e}"

    def download_pdf_from_url(self, url: str) -> str:
        try:
            response = requests.get(url, stream=True)
            response.raise_for_status()
            
            parsed_url = urlparse(url)
            path = unquote(parsed_url.path)
            filename = Path(path).name
            
            if not filename or not filename.endswith('.pdf'):
                filename = 'downloaded_pdf.pdf'
            
            temp_dir = tempfile.gettempdir()
            local_path = os.path.join(temp_dir, filename)
            
            with open(local_path, 'wb') as f:
                for chunk in response.iter_content(chunk_size=8192):
                    f.write(chunk)
            
            print(f"PDFをダウンロードしました: {local_path}")
            return local_path
        except Exception as e:
            raise Exception(f"PDFダウンロードに失敗しました: {e}")

    def convert_pdf_to_markdown(self, pdf_path: str, output_path: Optional[str] = None):
        if not output_path:
            output_path = pdf_path.replace('.pdf', '.md')
        
        print(f"PDF処理開始: {pdf_path}")
        pages_data = self.extract_pdf_content(pdf_path)
        
        print("OpenAI APIで要約生成中...")
        markdown_content = self.generate_markdown_summary(pages_data)
        
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(markdown_content)
        
        print(f"Markdownファイル作成完了: {output_path}")
        return output_path

def main():
    if len(sys.argv) < 2:
        print("使用法: python pdf2md.py <PDFファイルパスまたはURL> [出力ファイルパス]")
        sys.exit(1)
    
    input_path = sys.argv[1]
    output_path = sys.argv[2] if len(sys.argv) > 2 else None
    
    try:
        converter = PDF2MDConverter()
        
        if input_path.startswith('http://') or input_path.startswith('https://'):
            print(f"URLからPDFをダウンロード中: {input_path}")
            pdf_path = converter.download_pdf_from_url(input_path)
            
            if not output_path:
                parsed_url = urlparse(input_path)
                path = unquote(parsed_url.path)
                filename = Path(path).stem
                if not filename:
                    filename = 'downloaded_pdf'
                output_path = f"{filename}.md"
        else:
            pdf_path = input_path
        
        converter.convert_pdf_to_markdown(pdf_path, output_path)
        
        if input_path.startswith('http://') or input_path.startswith('https://'):
            os.remove(pdf_path)
            print(f"一時ファイルを削除しました: {pdf_path}")
        
    except Exception as e:
        print(f"エラー: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
