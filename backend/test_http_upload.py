"""通过 HTTP 测试上传（获取精确错误信息）"""
import httpx

url = "http://localhost:8000/api/v1/literatures/upload"
with open("test_doc.pdf", "rb") as f:
    content = f.read()

files = {"file": ("test_doc.pdf", content, "application/pdf")}
data = {"title": "test"}

resp = httpx.post(url, files=files, data=data)
print("Status:", resp.status_code)
print("Body:", resp.text)
