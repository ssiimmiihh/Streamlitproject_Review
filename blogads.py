# -*- coding: utf-8 -*-
import streamlit as st
import urllib.request
import urllib.parse
import json
import pandas as pd
from datetime import datetime
import sqlite3
import os
from openai import OpenAI

os.environ["LANGSMITH_TRACING"] = "true"  # 추적 활성화
os.environ["LANGSMITH_ENDPOINT"] = "https://api.smith.langchain.com"  # 엔드포인트
os.environ["LANGSMITH_API_KEY"] = "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"  # 발급받은 API 키 입력

# 선택 사항
os.environ["LANGSMITH_PROJECT"] = "naver_shopping_ai"  # 프로젝트 이름 (설정하지 않으면 "default"로 지정됨)
os.environ["OPENAI_API_KEY"] = "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"  # OpenAI API 키

# 페이지 설정
st.set_page_config(
    page_title="광고 없는 찐 리뷰 확인하기",
    page_icon="📍",
    layout="wide"
)

# NaverApiClient 클래스 정의
class NaverApiClient:
    def __init__(self, client_id, client_secret):
        self.client_id = client_id
        self.client_secret = client_secret
        self.base_url = "https://openapi.naver.com/v1/search/"
   
    def get_data(self, media, count, query, start=1, sort="date"):
        """
        네이버 API에서 데이터를 가져오는 메소드
        """
        encText = urllib.parse.quote(query)
        url = f"{self.base_url}{media}?sort={sort}&display={count}&start={start}&query={encText}"
       
        request = urllib.request.Request(url)
        request.add_header("X-Naver-Client-Id", self.client_id)
        request.add_header("X-Naver-Client-Secret", self.client_secret)
       
        try:
            response = urllib.request.urlopen(request)
            rescode = response.getcode()
           
            if(rescode==200):
                response_body = response.read()
                result = response_body.decode('utf-8')
                return result
            else:
                st.error(f"Error Code: {rescode}")
                return None
        except Exception as e:
            st.error(f"Exception occurred: {e}")
            return None
   
    def get_blog(self, query, count=10, start=1, sort="date"):
        """블로그 검색 결과를 가져오는 편의 메소드"""
        return self.get_data("blog", count, query, start, sort)
   
    def parse_json(self, data):
        """API 응답을 JSON으로 파싱하는 메소드"""
        if data:
            return json.loads(data)
        return None

# 데이터베이스 초기화 및 연결 함수
def init_db():
    # 데이터베이스 디렉토리 확인 및 생성
    db_dir = os.path.join(os.getcwd(), "data")
    if not os.path.exists(db_dir):
        os.makedirs(db_dir)
   
    db_path = os.path.join(db_dir, "reviews.db")
   
    # 데이터베이스 연결
    conn = sqlite3.connect(db_path)
    c = conn.cursor()
   
    # 테이블 생성 (없는 경우)
    c.execute('''
    CREATE TABLE IF NOT EXISTS blog_posts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        product_name TEXT NOT NULL,
        title TEXT NOT NULL,
        description TEXT,
        link TEXT,
        blogger_name TEXT,
        post_date TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    ''')
   
    # 분석 결과 테이블 생성
    c.execute('''
    CREATE TABLE IF NOT EXISTS analysis_results (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        product_name TEXT NOT NULL,
        positive_opinions TEXT,
        negative_opinions TEXT,
        summary TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    ''')
   
    conn.commit()
    return conn, c

# 블로그 데이터를 DB에 저장하는 함수
def save_blog_data_to_db(conn, cursor, blog_data, product_name):
    if not blog_data or "items" not in blog_data or not blog_data["items"]:
        st.warning("처리할 블로그 데이터가 없습니다.")
        return 0
   
    # 기존 데이터 삭제 (같은 제품명으로 검색한 경우)
    cursor.execute("DELETE FROM blog_posts WHERE product_name = ?", (product_name,))
   
    # 새 데이터 삽입
    count = 0
    for item in blog_data["items"]:
        # HTML 태그 제거
        title = item["title"].replace("<b>", "").replace("</b>", "").replace("&quot;", '"')
        description = item["description"].replace("<b>", "").replace("</b>", "").replace("&quot;", '"')
       
        cursor.execute('''
        INSERT INTO blog_posts (product_name, title, description, link, blogger_name, post_date)
        VALUES (?, ?, ?, ?, ?, ?)
        ''', (
            product_name,
            title,
            description,
            item.get("link", ""),
            item.get("bloggername", ""),
            item.get("postdate", "")
        ))
        count += 1
   
    conn.commit()
    st.success(f"{count}개의 블로그 포스트가 데이터베이스에 저장되었습니다.")
    return count

# 데이터베이스에서 블로그 포스트 가져오기
def get_blog_posts(cursor, product_name, limit=50):
    cursor.execute("""
    SELECT title, description, blogger_name, post_date, link
    FROM blog_posts
    WHERE product_name = ?
    LIMIT ?
    """, (product_name, limit))
   
    return cursor.fetchall()

# 분석 결과를 데이터베이스에 저장
def save_analysis_result(conn, cursor, product_name, positive, negative, summary):
    # 기존 분석 삭제 (같은 제품명인 경우)
    cursor.execute("DELETE FROM analysis_results WHERE product_name = ?", (product_name,))
   
    # 새 분석 결과 저장
    cursor.execute('''
    INSERT INTO analysis_results (product_name, positive_opinions, negative_opinions, summary)
    VALUES (?, ?, ?, ?)
    ''', (product_name, positive, negative, summary))
   
    conn.commit()

# 데이터베이스에서 분석 결과 가져오기
def get_analysis_result(cursor, product_name):
    cursor.execute("""
    SELECT positive_opinions, negative_opinions, summary
    FROM analysis_results
    WHERE product_name = ?
    """, (product_name,))
   
    return cursor.fetchone()

# ChatGPT API를 사용한 리뷰 분석 함수
def analyze_reviews(api_key, reviews_text, product_name):
    if not api_key:
        st.error("OpenAI API 키가 필요합니다.")
        return None, None, None
   
    try:
        # OpenAI 모듈 가져오기
        import openai
       
        # API 키 설정
        openai.api_key = api_key
       
        # 리뷰 텍스트가 너무 긴 경우 줄이기
        max_chars = 15000
        if len(reviews_text) > max_chars:
            st.warning(f"리뷰 텍스트가 너무 깁니다. 처음 {max_chars} 문자만 분석합니다.")
            reviews_text = reviews_text[:max_chars] + "... (이하 생략)"
       
        # 리뷰 분석을 위한 프롬프트
        prompt = f"""
            다음은 '{product_name}'에 대한 네이버 블로그 포스트입니다. 해당 콘텐츠를 철저히 분석하여 아래 요청사항에 따라 응답해주세요:

            1. 광고성 콘텐츠 식별:
            - 먼저 제공된 글이 광고성 콘텐츠인지 객관적으로 판단해주세요.
            - 판단 기준: 협찬/광고 문구 명시, 지나치게 긍정적인 어조, 구매 링크 다수 포함, 상품 홍보에 치중된 내용 등
            - 광고성 콘텐츠로 판단되면 해당 내용은 의견 분석에서 제외하거나 비중을 낮춰주세요.

            2. 긍정적 의견 분석:
            - 실제 사용자가 직접 경험한 구체적인 장점을 중심으로 분석해주세요.
            - 객관적 사실과 주관적 만족도를 구분하여 서술해주세요.
            - 가장 자주 언급되는 긍정적 특징을 우선적으로 포함해주세요.
            - 5-7줄로 간결하게 요약해주세요.

            3. 부정적 의견 분석:
            - 실제 사용자의 불만사항과 개선점을 중심으로 분석해주세요.
            - 단순한 불평이 아닌 구체적인 단점과 문제점에 초점을 맞춰주세요.
            - 가장 자주 언급되는 부정적 특징을 우선적으로 포함해주세요.
            - 5-7줄로 간결하게 요약해주세요.
            - 부정적 의견이 거의 없는 경우, 그 이유(광고성 글이 많은지, 제품이 실제로 만족도가 높은지 등)를 분석해주세요.

            4. 종합 평가:
            - 긍정/부정 의견의 비율과 신뢰도를 고려한 균형 잡힌 총평을 제공해주세요.
            - 광고성 콘텐츠의 비중을 고려하여 실제 사용자 의견이 얼마나 반영되었는지 언급해주세요.
            - 제품의 주요 특징과 사용자 만족도를 객관적으로 평가해주세요.
            - 5-7줄로 간결하게 요약해주세요.

            블로그 내용:
            {reviews_text}

            응답은 JSON 형식으로 제공하되  Markdown출력은 사용하지 말아주세요:
            {{
            "ad_analysis": "광고성 콘텐츠 분석 결과 (광고성 콘텐츠 비율 추정치 포함)",
            "positive": "구체적인 긍정적 의견 요약 (실제 사용자 경험 중심)",
            "negative": "구체적인 부정적 의견 요약 (실제 사용자 경험 중심)",
            "summary": "객관적인 전체 요약 및 종합 평가"
            }}
            """

        # API 호출
        client = OpenAI(api_key=api_key)
        
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "당신은 제품 리뷰 분석 전문가입니다. 제공된 콘텐츠를 철저히 분석하여 광고성 글을 식별하고, 실제 사용자 경험에 기반한 정보를 추출하는 능력이 있습니다. 분석 시 객관적 근거를 바탕으로 추론하고, 긍정/부정 의견의 패턴을 파악하여 명확하게 구분합니다. 단순 요약이 아닌 심층적 분석을 제공하며, 신뢰할 수 있는 종합 평가를 제시합니다."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.2,
            max_tokens=2048
        )

       
        # 결과 파싱
        content = response.choices[0].message.content.strip()
        # st.write("응답 내용 원본:\n", content)

        if not content:
            st.error("ChatGPT 응답이 비어 있습니다.")
            return None, None, None

        try:
            result = json.loads(content)
            return result["positive"], result["negative"], result["summary"]
        except json.JSONDecodeError as e:
            st.error(f"JSON 파싱 오류 발생: {str(e)}")
            st.text_area("응답 원문 보기", content, height=300)
            return None, None, None
   
    except Exception as e:
        st.error(f"ChatGPT API 호출 중 오류 발생: {str(e)}")
        return None, None, None

# 메인 애플리케이션 함수
def main():
    #st.title("Naver Blog 제품 리뷰 분석 코파일럿 ")
    st.markdown("""
    <div style="background-color: #f9f9f9; padding: 20px; border-radius: 10px; text-align: center;">
        <span style="color: #03c75a; font-size: 40px; font-weight: bold;">Naver Blog </span>
        <span style="color: #000000; font-size: 35px; font-weight: bold;">  제품 리뷰 분석 코파일럿</span>
    </div>
    """, unsafe_allow_html=True)

        
    # 사이드바 설정
    with st.sidebar:
        st.header("API 설정")
       
        # 네이버 API 설정
        st.subheader("네이버 검색 API")
        naver_client_id = st.text_input("Naver Client ID", value="9XhhxLV1IzDpTZagoBr1")
        naver_client_secret = st.text_input("Naver Client Secret", value="J14HFxv3B6", type="password")
       
        # OpenAI API 설정
        st.subheader("OpenAI API")
        openai_api_key = st.text_input("OpenAI API 키", type="password")
       
        st.markdown("---")
       
        # 데이터베이스 초기화 버튼
        st.subheader("데이터베이스 설정")
        reset_db_button = st.button("데이터베이스 초기화")
       
        if reset_db_button:
            # 데이터베이스 파일 삭제
            db_path = os.path.join(os.getcwd(), "data", "reviews.db")
            if os.path.exists(db_path):
                os.remove(db_path)
                st.success("데이터베이스가 초기화되었습니다.")
   
    # 데이터베이스 연결
    conn, cursor = init_db()
   
    # 네이버 API 클라이언트 생성
    naver_client = NaverApiClient(naver_client_id, naver_client_secret)
   
    
# 제품명 입력 및 검색 설정
    st.markdown("##")
    st.subheader("제품 검색 및 분석")
   
    product_name = st.text_input("제품명 입력", "")
   
    col1, col2 = st.columns([2, 2])
   
    with col1:
        count = st.slider("검색 결과 수", min_value=10, max_value=100, value=50)
   
    with col2:
        sort_options = st.selectbox(
            "정렬",
            options=[("최신순", "date"), ("정확도순", "sim")],
            format_func=lambda x: x[0]
        )
        sort_option = sort_options[1]
   
    # 검색 및 분석 버튼 배치
    with col1:
        search_col, analyze_col = st.columns(2)
        with search_col:
            search_button = st.button("검색", type="primary")
        with analyze_col:
            analyze_button = st.button("분석")
    
    # 검색 버튼 처리
    if search_button and product_name:
        if not naver_client_id or not naver_client_secret:
            st.error("네이버 API 키가 필요합니다.")
        else:
            with st.spinner(f"'{product_name}'에 대한 네이버 블로그 검색 중..."):
                # 네이버 블로그 검색
                data = naver_client.get_blog(product_name, count, sort=sort_option)
                parsed_data = naver_client.parse_json(data)
            
                if parsed_data and "items" in parsed_data and parsed_data["items"]:
                    # 블로그 데이터를 DB에 저장
                    save_blog_data_to_db(conn, cursor, parsed_data, product_name)
                
                    # 검색 결과 표시
                    st.subheader(f"검색 결과 (총 {parsed_data['total']}개 중 {len(parsed_data['items'])}개 표시)")
                
                    # 결과를 데이터프레임으로 표시
                    df = pd.DataFrame(parsed_data["items"])
                
                    # HTML 태그 제거
                    for col in ['title', 'description']:
                        if col in df.columns:
                            df[col] = df[col].str.replace('<b>', '').str.replace('</b>', '').str.replace('&quot;', '"')
                
                    # 필요한 열만 선택하여 표시
                    display_cols = ['title', 'description', 'postdate', 'bloggername']
                    display_cols = [col for col in display_cols if col in df.columns]
                
                    st.dataframe(df[display_cols], use_container_width=True)
                    
                    # 검색 결과가 있음을 세션 상태에 저장
                    st.session_state.search_results_available = True
                    st.session_state.current_product = product_name
                else:
                    st.error("검색 결과가 없거나 오류가 발생했습니다.")
                    st.session_state.search_results_available = False

    # 분석 버튼 처리
    if (analyze_button or st.session_state.get("analyze_clicked", False)) and st.session_state.get("search_results_available", False):
        # 분석 버튼을 클릭했음을 기록
        st.session_state.analyze_clicked = True
        
        if not openai_api_key:
            st.error("OpenAI API 키가 필요합니다.")
        else:
            st.markdown("---")
            st.subheader("리뷰 분석")
            st.markdown(f"**'{st.session_state.current_product}'** 에 대한 블로그 리뷰를 분석합니다.")
            st.markdown("---")
            
            # 먼저 기존 분석 결과가 있는지 확인
            existing_analysis = get_analysis_result(cursor, st.session_state.current_product)
           
            if existing_analysis and not st.session_state.get("reanalyze", False):
                # 기존 분석 결과 표시
                positive, negative, summary = existing_analysis
               
                # 분석 결과 표시
                st.subheader("기존 분석 결과")
                col1, col2 = st.columns(2)
               
                with col1:
                    st.markdown("### 👍 긍정적 의견")
                    st.markdown(positive)
               
                with col2:
                    st.markdown("### 👎 부정적 의견")
                    st.markdown(negative)
               
                st.markdown("### 📋 전체 요약 및 총평")
                st.markdown(summary)
               
                # 재분석 옵션
                if st.button("재분석 실행"):
                    if "reanalyze" not in st.session_state:
                        st.session_state["reanalyze"] = False
                    st.session_state["reanalyze"] = True
                    st.rerun()
            else:
                with st.spinner("리뷰 데이터 분석 중..."):
                    # DB에서 블로그 포스트 가져오기
                    blog_posts = get_blog_posts(cursor, st.session_state.current_product)
                   
                    if blog_posts:
                        # 모든 블로그 포스트 내용 결합
                        all_posts_text = "\n\n".join([
                            f"제목: {post[0]}\n내용: {post[1]}\n작성자: {post[2]}\n날짜: {post[3]}"
                            for post in blog_posts
                        ])
                       
                        # ChatGPT로 리뷰 분석
                        positive, negative, summary = analyze_reviews(openai_api_key, all_posts_text, st.session_state.current_product)
                       
                        if positive and negative and summary:
                            # 분석 결과 DB에 저장
                            save_analysis_result(conn, cursor, st.session_state.current_product, positive, negative, summary)
                           
                            # 분석 결과 표시
                            st.subheader("리뷰 분석 결과")
                            col1, col2 = st.columns(2)
                           
                            with col1:
                                st.markdown("### 👍 긍정적 의견")
                                st.markdown(positive)
                           
                            with col2:
                                st.markdown("### 👎 부정적 의견")
                                st.markdown(negative)
                           
                            st.markdown("### 📋 전체 요약 및 총평")
                            st.markdown(summary)
                           
                            # 세션 상태 초기화
                            st.session_state.reanalyze = False
                        else:
                            st.error("리뷰 분석 중 오류가 발생했습니다.")
                    else:
                        st.warning(f"'{st.session_state.current_product}'에 대한 블로그 포스트가 없습니다. 먼저 검색을 실행해주세요.")
   
    # 데이터베이스 연결 종료
    conn.close()
    
    # 광고 배너 토글 기능 추가
    show_ad = st.session_state.get("show_ad", True)
    
    # 광고 표시 영역
    st.markdown("---")
    ad_container = st.container()
    
    # 광고 컨텐츠 표시
    if show_ad:
        with ad_container:
            st.markdown("""
            <div style="border: 1px solid #ddd; border-radius: 5px; padding: 15px; margin-top: 10px;">
                <h3 style="margin-top: 0;">🔍 추천 제품</h3>
                <div style="display: flex; align-items: center;">
                    <a href="https://www.coupang.com/vp/products/6795965704?itemId=12628460347&vendorItemId=79896126181&q=%ED%95%98%EB%A6%BC+%EB%8B%AD%EA%B0%80%EC%8A%B4%EC%82%B4&itemsCount=36&searchId=7e7113a8513528&rank=3&searchRank=3&isAddedCart=" target="_blank">
                        <img src="//thumbnail9.coupangcdn.com/thumbnails/remote/492x492ex/image/retail/images/126526801505257-027701fa-b2f6-4323-997b-00dbe9c1b207.jpg" alt="하림 블랙페퍼 닭가슴살" style="width: 120px; height: 120px; object-fit: cover; margin-right: 16px; border-radius: 4px;">
                    </a>
                    <div>
                        <h4 style="margin: 0; color: #1a73e8; font-size: 25px;">하림 블랙페퍼 닭가슴살(냉장) 8개입 </h4>
                        <p style="margin: 4px 0 0; font-size: 20px;">무료배송, 모레(금) 도착 예정</p>
                        </div>
                    </div>
                </div>
            </div>
            """, unsafe_allow_html=True)

# 애플리케이션 실행
if __name__ == "__main__":
    # 세션 상태 초기화
    if "reanalyze" not in st.session_state:
        st.session_state.reanalyze = False
    if "search_results_available" not in st.session_state:
        st.session_state.search_results_available = False
    if "current_product" not in st.session_state:
        st.session_state.current_product = ""
    if "analyze_clicked" not in st.session_state:
        st.session_state.analyze_clicked = False
    if "show_ad" not in st.session_state:
        st.session_state.show_ad = True
        
    main()
