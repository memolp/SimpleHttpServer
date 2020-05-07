# -*- coding:utf-8 -*-

"""
  封装select，支持py3的模块
"""

import select

EVENT_READ = 1

class SelectorKey:
    def __init__(self, sock, mask, data):
        """ """
        self.sock = sock
        self.mask = mask
        self.data = data

class DefaultSelector():
    def __init__(self):
        """ """
        self.__rsocklist = {}

    def register(self, fd, mask, data):
        """
        注册
        """
        if mask != EVENT_READ:
            return
        self.__rsocklist[fd] = SelectorKey(fd, mask, data)

    def unregister(self, fd):
        """
        取消注册
        """
        if fd in self.__rsocklist:
            del self.__rsocklist[fd]

    def select(self,timeout=None):
        """ """
        sock_list = self.__rsocklist.keys()
        if len(sock_list) <= 0:
            return []
        if timeout:
            rbuf,_,_ = select.select(sock_list, [], [], timeout)
        else:
            rbuf,_,_ = select.select(sock_list, [], [])
        
        events = []
        for fd in rbuf:
            if fd in self.__rsocklist:
                obj = self.__rsocklist[fd]
                events.append((obj, EVENT_READ))
        return events