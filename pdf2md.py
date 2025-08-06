#!/usr/bin/env python3
import os
import sys
import argparse
import pdfplumber
import requests
from openai import OpenAI
from PIL import Image
import io
import base64
import json
from pathlib import Path

class PDF2MD:
    def __init__(self):
        self.gyazo_token = os.getenv('GYAZO_TOKEN')
        self.openai_api_key = os.getenv('OPENAI_API_KEY')
        
        if not self.gyazo_token:
            raise ValueError("GYAZO_TOKEN environment variable is required")
        if not self.openai_api_key:
            raise ValueError("OPENAI_API_KEY environment variable is required")
        
        self.client = OpenAI(api_key=self.openai_api_key)
    
    def extract_pdf_content_with_layout(self, pdf_path):
        """PDFからテキストと画像を位置情報と共に抽出"""
        pages_data = []
        
        with pdfplumber.open(pdf_path) as pdf:
            for page_num, page in enumerate(pdf.pages):
                page_elements = []
                
                # テキストを行ごとに抽出（位置情報付き）
                lines = page.extract_text_lines()
                for line in lines:
                    page_elements.append({
                        'type': 'text',
                        'content': line['text'],
                        'bbox': (line['x0'], line['top'], line['x1'], line['bottom']),
                        'y_pos': line['top']
                    })
                
                # 画像抽出（位置情報付き）
                print(f"Page {page_num + 1}: 画像検索中...")
                if hasattr(page, 'images') and page.images:
                    print(f"  発見した画像: {len(page.images)}個")
                    for img_idx, img in enumerate(page.images):
                        print(f"  画像 {img_idx + 1}: {img['name']} ({img['width']}x{img['height']})")
                        try:
                            # dict形式の画像オブジェクトから座標を取得
                            bbox = (img['x0'], img['y0'], img['x1'], img['y1'])
                            print(f"    bbox: {bbox}")
                            
                            image_obj = page.crop(bbox).to_image()
                            page_elements.append({
                                'type': 'image',
                                'image': image_obj.original,
                                'bbox': bbox,
                                'y_pos': bbox[1],  # top position
                                'page': page_num + 1,
                                'index': img_idx
                            })
                            print(f"    抽出成功")
                        except Exception as e:
                            print(f"    画像抽出エラー: {e}")
                else:
                    print(f"  画像なし")
                
                # Y位置でソート（上から下の順）
                page_elements.sort(key=lambda x: x['y_pos'])
                
                pages_data.append({
                    'page_num': page_num + 1,
                    'elements': page_elements
                })
        
        return pages_data
    
    def upload_to_gyazo(self, image):
        """画像をGyazoにアップロード"""
        # PILImageをbytesに変換
        img_byte_arr = io.BytesIO()
        image.save(img_byte_arr, format='PNG')
        img_byte_arr = img_byte_arr.getvalue()
        
        url = "https://upload.gyazo.com/api/upload"
        files = {'imagedata': ('image.png', img_byte_arr, 'image/png')}
        data = {'access_token': self.gyazo_token}
        
        try:
            response = requests.post(url, files=files, data=data)
            response.raise_for_status()
            return response.json()['url']
        except Exception as e:
            print(f"Gyazoアップロードエラー: {e}")
            return None
    
    def build_structured_content(self, pages_data, image_urls):
        """ページ構造を考慮してコンテンツを構築"""
        structured_content = ""
        image_counter = 0
        
        for page_data in pages_data:
            page_num = page_data['page_num']
            structured_content += f"\n\n--- Page {page_num} ---\n"
            
            for element in page_data['elements']:
                if element['type'] == 'text':
                    structured_content += element['content'] + "\n"
                elif element['type'] == 'image':
                    if image_counter < len(image_urls) and image_urls[image_counter]:
                        structured_content += f"\n[画像 {image_counter + 1}: Page {page_num}]\n![Image](<!-- IMAGE_PLACEHOLDER_{image_counter} -->)\n\n"
                        image_counter += 1
                    else:
                        structured_content += f"\n[画像: Page {page_num} - アップロード失敗]\n\n"
        
        return structured_content

    def summarize_with_openai(self, pages_data, image_urls):
        """OpenAI APIでページ構造を考慮して要約・構造化"""
        # 構造化されたコンテンツを構築
        structured_content = self.build_structured_content(pages_data, image_urls)
        
        # 実際にアップロードされた画像の数を確認
        valid_image_count = len([url for url in image_urls if url])
        
        if valid_image_count == 0:
            image_instruction = """
重要: このPDFには画像がないか、画像の抽出に失敗しました。
画像に関する言及や参照は一切しないでください。
実在しない図表やイラストについて言及することは禁止です。
テキスト内容のみに基づいて要約してください。"""
        else:
            image_instruction = f"""
このPDFには{valid_image_count}個の画像が含まれています。
画像とテキストの関連性を保ちながら、適切な箇所に画像を配置してください。
実際に抽出された画像のみを参照し、存在しない画像については言及しないでください。"""
        
        prompt = f"""以下のPDF内容を日本語でわかりやすく要約し、Markdown形式で構造化してください。

{image_instruction}

要約の際は以下を考慮してください：
- 文書の全体的な構造と流れを把握する
- ページごとの内容を統合して論理的な構造にする
- 存在しない情報や画像について推測や創造をしない

出力形式：
# 文書の概要

# 主要なポイント
- 重要なポイント1
- 重要なポイント2

# 詳細内容
## セクション1
内容の説明

## セクション2
内容の説明

PDF内容:
{structured_content}
"""
        
        response = self.client.chat.completions.create(
            model="gpt-4.1-mini",  # DESIGN.mdの指示通り
            messages=[
                {"role": "user", "content": prompt}
            ],
            temperature=0.3
        )
        
        # 画像プレースホルダーを実際のURLに置換
        result = response.choices[0].message.content
        for i, url in enumerate(image_urls):
            if url:
                result = result.replace(f"<!-- IMAGE_PLACEHOLDER_{i} -->", url)
        
        return result
    
    def convert(self, input_pdf, output_md):
        """メイン変換処理"""
        print(f"PDFを解析中: {input_pdf}")
        pages_data = self.extract_pdf_content_with_layout(input_pdf)
        
        # 全画像を収集
        images = []
        for page_data in pages_data:
            for element in page_data['elements']:
                if element['type'] == 'image':
                    images.append(element)
        
        if not any(page_data['elements'] for page_data in pages_data):
            print("警告: PDFからコンテンツが抽出できませんでした")
        
        print(f"画像を処理中: {len(images)}個の画像を発見")
        image_urls = []
        for img_data in images:
            print(f"  Page {img_data['page']} の画像をGyazoにアップロード中...")
            url = self.upload_to_gyazo(img_data['image'])
            if url:
                image_urls.append(url)
                print(f"    アップロード完了: {url}")
            else:
                image_urls.append(None)
                print(f"    アップロード失敗")
        
        print("OpenAI APIで要約中...")
        markdown_content = self.summarize_with_openai(pages_data, image_urls)
        
        # Markdownファイルに保存
        with open(output_md, 'w', encoding='utf-8') as f:
            f.write(markdown_content)
        
        print(f"変換完了: {output_md}")

def main():
    parser = argparse.ArgumentParser(description='PDF to Markdown converter')
    parser.add_argument('input', help='Input PDF file')
    parser.add_argument('output', help='Output Markdown file')
    
    args = parser.parse_args()
    
    if not os.path.exists(args.input):
        print(f"エラー: 入力ファイルが見つかりません: {args.input}")
        sys.exit(1)
    
    try:
        converter = PDF2MD()
        converter.convert(args.input, args.output)
    except Exception as e:
        print(f"エラー: {e}")
        sys.exit(1)

if __name__ == '__main__':
    main()
