# -*- coding:utf-8 -*-

"""
  一个简单的Http服务器，支持POST，GET方法
"""

import os
import logging
import socket
import urlparse
import traceback

# 这两个模块写的比较简单，最好是自己重新实现。
import selectors
import thread_pool


class SimpleHttpServer:
    """
    Http 服务器
    """
    MAX_LISTEN_WAIT_COUNT = 5
    # 响应请求处理类
    request_handlers = {}
    # 静态资源存放路径
    static_resource_path = ""
    def __init__(self, host, port=80):
        """
        创建Http服务器
        @param: host为绑定服务器ip
        @param: port服务器端口 默认80
        """
        self.http_host = host
        self.http_port = port
        self.http_running = False
        # 线程池
        self.http_pool = thread_pool.ThreadExecutor(4)
        # I/O多路复用
        self.sock_selector = selectors.DefaultSelector()
        # 服务器socket
        self.http_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)

    def _setup_server(self):
        """
        配置服务
        """
        if not self.http_sock:
            return False
        try:
            # 绑定服务器地址端口
            self.http_sock.bind((self.http_host, self.http_port))
            # 设置监听
            self.http_sock.listen(self.MAX_LISTEN_WAIT_COUNT)
            # 设置接收缓存大小
            self.http_sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 65535)
            # 禁用N算法
            self.http_sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, True)
            # 注册socket
            ex_data = {"address":(self.http_host, self.http_port), "callback":self._on_new_connected}
            self.sock_selector.register(self.http_sock, selectors.EVENT_READ, ex_data)
        except Exception as e:
            logging.error("[HTTP] (server) traceback:%s" % traceback.format_exc())
            return False
        return True        

    def _start_forever(self):
        """
        进入死循环
        """
        logging.info("[HTTP] start on http://%s:%s"%(self.http_host, self.http_port))
        logging.info("[HTTP] ctrl + c to quit")
        while self.http_running:
            try:
                events = self.sock_selector.select(0.1)
                for obj, mask in events:
                    callback = obj.data["callback"]
                    self.sock_selector.unregister(obj.sock)
                    self.http_pool.submit(callback, obj.sock, obj.data)
            except KeyboardInterrupt as e:
                self.http_running = False
    
    def _on_new_connected(self, sock, data):
        """ 
        新连接过来时调用
        """
        client, address = sock.accept()
        ex_data = {"address":address, "callback":self._on_client_request}
        self.sock_selector.register(client, selectors.EVENT_READ, ex_data)
        self.sock_selector.register(sock, selectors.EVENT_READ, data)
        

    def _on_client_request(self, sock, data):
        """
        客户端请求过来
        """
        request = RequestResolver.on_request_parser(sock, data['address'])
        if not request:
            sock.close()
            return
        self._handler_request(request, sock, data)
        if not request.keepAlive:
            sock.close()
        else:
            self.sock_selector.register(sock, selectors.EVENT_READ, data)

    def _handler_request(self, requset, sock, data):
        """ """
        try:
            handler = self.request_handlers.get(requset.location, StaticRequestHandler)
            obj = handler(requset)
            request_method = getattr(obj, requset.method, None)
            if not request_method:
                logging.info("[HTTP] (server) location:%s  403" % requset.location)
                obj.write_error(403, "This method Forbidden")
                obj.flush()
                return
            try:
                request_method()
            except Exception as e:
                logging.error("[HTTP] (server) server call method error :%s" % traceback.format_exc())
            finally:
                logging.info("[HTTP] (server) location:%s  code:%s" % (requset.location, obj.code))
                obj.flush()
        except Exception as e:
            logging.error("[HTTP] (server) server  error :%s" % traceback.format_exc())

    def start_server(self, handlers, static_path, debug=False):
        """
        启动服务
        """
        SimpleHttpServer.request_handlers = handlers
        SimpleHttpServer.static_resource_path = static_path
        if debug:
            logging.basicConfig(level=logging.NOTSET)
        if not self._setup_server():
            return False
        self.http_running = True
        self._start_forever()
        return True

class RequestResolver:
    """ 请求分析类 """
    @staticmethod
    def on_parse_request(request):
        """ 解析首行 """
        first_line = request.rfile.readline()
        if not first_line: # 说明客户端已经主动断开连接
            return False
        # GET/POST/HEAD url&args HTTP/1.1
        method_location_version = first_line.split()
        if len(method_location_version) != 3:
            logging.error("[HTTP] (Resolver) first line format error!")
            return False
        # 存储对应数据
        method, route, version = method_location_version
        if version == "HTTP/1.0" or version == "HTTP/1.1": 
            request.method = method.lower()
            request.route  = route
            request.version = version
            return True
        else:
            logging.error("[HTTP] (Resolver) this http version :%s unsupport!" % version)
            return False
    @staticmethod
    def on_parse_headers(request):
        """ 读取解析请求头 """
        while True:
            line = request.rfile.readline().strip()
            if not line :
                break
            name_value = line.split(": ", 1)
            if not name_value or len(name_value) != 2:
                logging.error("[HTTP] (Resolver) request head format error ! raw_data:%s" % line)
                return False
            name = name_value[0]
            value = name_value[1]
            request.headers[name] = value.strip()
        return True

    @staticmethod
    def on_parse_arguments(raw_body_data, request):
        """ 解析请求参数 """
        # url中存放参数 /xxxx?a=v1&b=v2...
        index = request.route.find("?")
        if index > 0 and len(request.route) > index:
            arguments = urlparse.parse_qs(request.route[index+1:])
            request.arguments.update(arguments)
            # 修改url，去掉参数
            request.location = request.route[:index]
        else:
            request.location = request.route
        # 解析请求内容的格式
        form_str_type = request.headers.get("Content-Type", None)
        if not form_str_type:
            return  # 如果没有指定类型则不理会了
        # 将参数放在正文中，但格式和放在url里面的一样
        if form_str_type.find("application/x-www-form-urlencoded") >= 0:
            arguments = urlparse.parse_qs(raw_body_data)
            request.arguments.update(arguments)
        # 将参数放在正文中，采用多附件表单格式
        elif form_str_type.find("multipart/form-data") >= 0:
            boundary_index = form_str_type.rfind("boundary=")
            if boundary_index < 0:
                logging.error("[HTTP] (Resolver) Invalid multipart/form-data: no boundary")
                return
            arguments, files = RequestResolver.parse_multipart_formdata(raw_body_data,form_str_type[boundary_index+len("boundary="):])
            request.arguments.update(arguments)
            request.files.update(files)
        else:
            logging.error("[HTTP] (Resolver) unsupport arguments type : %s" % form_str_type)

    @staticmethod
    def parse_multipart_formdata(raw_body_data, boundary):
        """
        解析multipart/form-data格式
        """
        arguments = {}
        files = {}

        if boundary.startswith('"') and boundary.endswith('"'):
            boundary = boundary[1:-1]
        final_boundary_index = raw_body_data.rfind("--" + boundary + "--")
        if final_boundary_index == -1:
            logging.error("[HTTP] (Resolver) Invalid multipart/form-data: no final boundary")
            return arguments, files

        parts = raw_body_data[:final_boundary_index].split("--" + boundary + "\r\n")
        for part in parts:
            if not part:
                continue
            # 获取参数头信息
            eoh = part.find("\r\n\r\n")
            if eoh == -1:
                logging.error("[HTTP] (Resolver) multipart/form-data missing headers")
                continue
            header_raw_str = part[:eoh]
            #Content-Disposition: form-data; name="file000"; filename="xxx"\r\nContent-Type: application/octet-stream
            header_attr_group = header_raw_str.split("\r\n")
            headers = {}
            for header_attr in header_attr_group:
                header_key_value = header_attr.split(":")
                if len(header_key_value) != 2:
                    continue
                key = header_key_value[0].strip()
                value = header_key_value[1].strip()
                headers[key] = value
            dis_hander = headers.get("Content-Disposition","")
            dis_header_attrs = dis_hander.split(";")
            disp_params= {}
            disposition = ""
            for header_attr in dis_header_attrs:
                if header_attr.find("=") < 0:
                    disposition = header_attr
                else:
                    attr_value = header_attr.split("=")
                    attr_name = attr_value[0].strip()
                    attr_value = attr_value[1].strip()
                    disp_params[attr_name] = attr_value
                    
            if disposition != "form-data":
                logging.error("[HTTP] (Resolver) Invalid multipart/form-data :%s only support form-data" % disposition)
                continue
            value = part[eoh + 4:-2]
            if not disp_params.get("name", None):
                logging.error("[HTTP] (Resolver) multipart/form-data value missing name")
                continue
            name = disp_params["name"]
            if disp_params.get("filename", None):
                mine_type = headers.get("Content-Type", "application/unknown")
                http_file = HTTPFile(filename=disp_params["filename"], body=value, content_type=mine_type)
                files.setdefault(name, []).append(http_file)
            else:
                arguments.setdefault(name, []).append(value)
        return arguments, files

    @staticmethod 
    def on_request_parser(sock, address):
        """ """
        try:
            request = HttpRequest(sock, address[0], address[1])
            # 解析第一行， 解析失败则返回关闭连接
            if not RequestResolver.on_parse_request(request):
                return 
            # 解析实体头
            if not RequestResolver.on_parse_headers(request):
                return 
            content_length = int(request.headers.get("Content-Length", "0"))
            raw_body_data = request.rfile.read(content_length) if content_length > 0 else bytes("")
            RequestResolver.on_parse_arguments(raw_body_data, request)
            # 真的长连接设置
            connection_type = request.headers.get("Connection", "close").lower()
            if connection_type == "keep-alive":
                request.keepAlive = True
            return request
        except Exception as e:
            logging.error("[HTTP] (Resolver) parse request error : %s" % traceback.format_exc())


class HTTPFile(object):
    """ 上传文件保存对象-注意这种实现方式不可上传过大文件，否则服务器内存有问题 """
    def __init__(self, filename, body, content_type):
        """ """
        self.filename = filename
        self.body = body
        self.minetype = content_type

class HttpRequest(object):
    """ HTTP 请求数据保存类 """
    def __init__(self, sock, _host, _port):
        """ """
        self.host = _host                       # 请求的ip地址
        self.port = _port                       # 请求的ip端口
        self.location = None                    # 请求地址-不包含参数
        self.route = None                       # 请求资源描述符，包含地址和参数
        self.method = None                      # 请求的方法，全小写存放
        self.version = None                     # HTTP的版本
        self.headers = {}                       # 请求的头信息
        self.cookies = {}                       # 请求中的Cookie信息
        self.arguments = {}                     # 请求中的参数数据
        self.files = {}                         # 请求中的文件数据
        self.keepAlive = False                  # 是否保持连接
        self.socket  = sock                     # 保存客户端socket对象
        self.rfile   = sock.makefile(mode="r")  # 保存客户端socket转文件读
        self.wfile   = sock.makefile(mode="w")  # 保存客户端socket转文件写

class RequestHandler(object):
    """ HTTP 请求处理接口类 """
    def __init__(self, _request):
        """ """
        self.request = _request
        self.version = None
        self.code = 200
        self.message = "OK"
        self.raw_data = bytes("")
        self.headers = {}

    def set_header(self, k, v):
        """ """
        self.headers[k] = v
    
    def write_header(self, code=200, message="OK"):
        """ """
        self.request.wfile.write("HTTP/1.1 {0} {1}\r\n".format(code, message))
        for k, v in self.headers.items():
            self.request.wfile.write("{0}: {1}\r\n".format(k,v))
        self.request.wfile.write("\r\n")
        
    def write_error(self, code, message, body=None):
        """
        错误响应
        """
        self.code = code
        self.message = message
        if body:
            self.write(body)
        else:
            self.write("<html><h2>{0}</h2><h3>{1}</h3></html>".format(code,message))

    def write(self, body):
        """
        写入数据，仅保存起来，一起发送出去
        """
        self.raw_data += body

    def flush(self):
        """
        解析请求的内容
        """
        if "Content-Length" not in self.headers:
            self.headers["Content-Length"] = len(self.raw_data)
        if "Content-Type" not in self.headers:
            self.headers["Content-Type"] = "text/html"
        self.write_header(self.code, self.message)
        self.request.wfile.write(self.raw_data)
        self.request.wfile.flush()

class StaticRequestHandler(RequestHandler):
    """ 静态资源请求方法 """
    def get(self):
        """ """
        filename = self.request.location[1:]
        path_name = os.path.join(SimpleHttpServer.static_resource_path, filename)
        if not os.path.exists(path_name):
            return self.write_error(404, "Not Found")
        if not os.path.isfile(path_name):
            return self.write_error(404, "Not Found")
        self.set_header("Content-Type", "application/oct-stream")
        with open(path_name, "rb") as pf:
            self.write(pf.read())
        