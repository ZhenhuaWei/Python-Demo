import pyttsx3

str = "1"
engine = pyttsx3.init("nsss")# nsss macϵͳ
rate = engine.getProperty('rate')
engine.setProperty('rate', rate+200)#�������� 
engine.say(str)
engine.runAndWait() # ���к͵ȴ���ʱ��ȽϾ� ���3�� �ﲻ���������ټ�ⰴ�����̰�������
str = "2"

engine.say(str)
engine.runAndWait()