# 온도 변환 마이크로 서비스 API

## 라우팅 규칙
- POST /convert 엔드포인트를 개설한다.
- 입력값 규칙 (JSON): {"temperature": 30, "type": "C"} (type은 C 또는 F)

## 비즈니스 로직
- type이 "C"이면 섭씨를 화씨로 변환하여 리턴한다.
- type이 "F"이면 화씨를 섭씨로 변환하여 리턴한다.
- 출력값 규칙 (JSON): {"result": 변환된_값}
