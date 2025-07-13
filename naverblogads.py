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

# 환경 변수 설정 (LangSmith는 유지)
os.environ["LANGSMITH_TRACING"] = "true"
os.environ["LANGSMITH_ENDPOINT"] = "https://api.smith.langchain.com"
os.environ["LANGSMITH_API_KEY"] = "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"  # 발급받은 LangSmith 키
os.environ["LANGSMITH_PROJECT"] = "naver_shopping_ai"

# Streamlit Secrets에서 API 키 가져오기
try:
    naver_client_id = st.secrets["NAVER_CLIENT_ID"]
    naver_client_secret = st.secrets["NAVER_CLIENT_SECRET"]
    openai_api_key = st.secrets["OPENAI_API_KEY"]
except Exception:
    st.error("Secrets를 불러오지 못했습니다. Streamlit Cloud 설정을 확인하세요.")
    st.stop()

os.environ["OPENAI_API_KEY"] = openai_api_key

# 페이지 설정
st.set_page_config(
    page_title="광고 없는 찐 리뷰 확인하기",
    page_icon="📍",
    layout="wide"
)

# --- 클래스 및 함수 정의는 기존과 동일하므로 생략 없이 유지 ---

# (NaverApiClient, init_db, save_blog_data_to_db, get_blog_posts,
# save_analysis_result, get_analysis_result, analyze_reviews 함수 동일)

# 메인 애플리케이션 함수
def main():
    st.markdown("""
    <div style="background-color: #f9f9f9; padding: 20px; border-radius: 10px; text-align: center;">
        <span style="color: #03c75a; font-size: 40px; font-weight: bold;">Naver Blog </span>
        <span style="color: #000000; font-size: 35px; font-weight: bold;">  제품 리뷰 분석 코파일럿</span>
    </div>
    """, unsafe_allow_html=True)

    # 🔄 DB 초기화 버튼 (사이드바에서 본문으로 이동)
    st.markdown("### 데이터베이스 설정")
    if st.button("데이터베이스 초기화"):
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
        with st.spinner(f"'{product_name}'에 대한 네이버 블로그 검색 중..."):
            data = naver_client.get_blog(product_name, count, sort=sort_option)
            parsed_data = naver_client.parse_json(data)

            if parsed_data and "items" in parsed_data and parsed_data["items"]:
                save_blog_data_to_db(conn, cursor, parsed_data, product_name)

                st.subheader(f"검색 결과 (총 {parsed_data['total']}개 중 {len(parsed_data['items'])}개 표시)")

                df = pd.DataFrame(parsed_data["items"])

                for col in ['title', 'description']:
                    if col in df.columns:
                        df[col] = df[col].str.replace('<b>', '').str.replace('</b>', '').str.replace('&quot;', '"')

                display_cols = ['title', 'description', 'postdate', 'bloggername']
                display_cols = [col for col in display_cols if col in df.columns]

                st.dataframe(df[display_cols], use_container_width=True)

                st.session_state.search_results_available = True
                st.session_state.current_product = product_name
            else:
                st.error("검색 결과가 없거나 오류가 발생했습니다.")
                st.session_state.search_results_available = False

    # 분석 버튼 처리
    if (analyze_button or st.session_state.get("analyze_clicked", False)) and st.session_state.get("search_results_available", False):
        st.session_state.analyze_clicked = True

        st.markdown("---")
        st.subheader("리뷰 분석")
        st.markdown(f"**'{st.session_state.current_product}'** 에 대한 블로그 리뷰를 분석합니다.")
        st.markdown("---")

        existing_analysis = get_analysis_result(cursor, st.session_state.current_product)

        if existing_analysis and not st.session_state.get("reanalyze", False):
            positive, negative, summary = existing_analysis

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

            if st.button("재분석 실행"):
                st.session_state["reanalyze"] = True
                st.rerun()
        else:
            with st.spinner("리뷰 데이터 분석 중..."):
                blog_posts = get_blog_posts(cursor, st.session_state.current_product)

                if blog_posts:
                    all_posts_text = "\n\n".join([
                        f"제목: {post[0]}\n내용: {post[1]}\n작성자: {post[2]}\n날짜: {post[3]}"
                        for post in blog_posts
                    ])

                    positive, negative, summary = analyze_reviews(openai_api_key, all_posts_text, st.session_state.current_product)

                    if positive and negative and summary:
                        save_analysis_result(conn, cursor, st.session_state.current_product, positive, negative, summary)

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

                        st.session_state.reanalyze = False
                    else:
                        st.error("리뷰 분석 중 오류가 발생했습니다.")
                else:
                    st.warning(f"'{st.session_state.current_product}'에 대한 블로그 포스트가 없습니다. 먼저 검색을 실행해주세요.")

    conn.close()

    show_ad = st.session_state.get("show_ad", True)

    st.markdown("---")
    ad_container = st.container()

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
