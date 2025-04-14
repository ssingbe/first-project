import pandas as pd
import os

def process_files(folder_path):
    # 파일 목록을 가져옵니다.
    files = [f for f in os.listdir(folder_path) if f.endswith('.csv') or f.endswith('.xlsx')]

    for file in files:
        # 파일을 읽어옵니다.
        file_path = os.path.join(folder_path, file)
        try:
            if file.endswith('.csv'):
                df = pd.read_csv(file_path)
            elif file.endswith('.xlsx'):
                df = pd.read_excel(file_path)
        except Exception as e:
            print(f"Error reading {file}: {e}")
            continue

        # 처음 10개와 마지막 10개의 행을 제거합니다.
        df = df[10:-10]
        
        # "단면적" 기준으로 상위 5%, 하위 5% 값 제거
        lower_5_percent = df['단면적'].quantile(0.05)
        upper_5_percent = df['단면적'].quantile(0.95)
        df = df[(df['단면적'] > lower_5_percent) & (df['단면적'] < upper_5_percent)]

        # 필요한 열들의 평균 값을 계산합니다.
        mean_2p_max_size = df['2P_max_size'].mean()
        mean_2p_min_size = df['2P_min_size'].mean()
        mean_cross_section = df['단면적'].mean()

        # 결과를 출력합니다.
        print(f"File: {file}")
        print(f"Mean 2P_max_size: {mean_2p_max_size}")
        print(f"Mean 2P_min_size: {mean_2p_min_size}")
        print(f"Mean 단면적: {mean_cross_section}")
        print('---------------------------')

if __name__ == "__main__":
    # 현재 스크립트 위치를 기준으로 new_folder 디렉토리의 절대 경로를 생성합니다.
    folder_path = '새폴더'

    process_files(folder_path)
    
    # 사용자가 결과를 확인할 시간을 줍니다.
    input("Press Enter to exit...")