# -*- coding:utf-8 -*-

"""
 简单HttpServer
"""
import os
import sys
# 加一个路径
sys.path.append("utils")

from SimpleHttpServer import SimpleHttpServer, RequestHandler

class IndexHandler(RequestHandler):
    def get(self):
        print(self.request.arguments)
        self.write("<a href='/login'>click to login</a>")

class LoginHandler(RequestHandler):
    def get(self):
        self.write("<html><form action='/login' method='POST'>\
                    <input name='username'>\
                    <input name='password'>\
                    <button type='submit'> submit </button>\
                    </form></html>")
    def post(self):
        print(self.request.arguments)
        self.write("<h2>login success</h2>")

class TestHandler(RequestHandler):
    def get(self):
        filename = os.path.join(SimpleHttpServer.static_resource_path, "test.html")
        with open(filename, "rb") as pf:
            self.write(pf.read())
        
    def post(self):
        print(self.request.arguments)
        self.write("hello")

def Main():
    """  """
    # 简单httpserver
    http_server = SimpleHttpServer("0.0.0.0")
    # 注册处理请求类
    handers = {}
    handers["/"] = IndexHandler
    handers["/index"] = IndexHandler
    handers["/login"] = LoginHandler
    handers["/test"] = TestHandler
    # 启动服务器
    http_server.start_server(handers, "./static", debug=True)


if __name__ == "__main__":
    Main()