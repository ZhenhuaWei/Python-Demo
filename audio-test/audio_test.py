import pyttsx3

str = "1"
engine = pyttsx3.init("nsss")# nsss mac系统
rate = engine.getProperty('rate')
engine.setProperty('rate', rate+200)#设置语速 
engine.say(str)
engine.runAndWait() # 运行和等待的时间比较久 大概3秒 达不到用来快速检测按键键盘按键报数
str = "2"

engine.say(str)
engine.runAndWait()