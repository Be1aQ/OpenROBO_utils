#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
OpenROBO utils

Copyright (c) 2017 r01hee

This software is released under the MIT License.
http://opensource.org/licenses/mit-license.php
"""

import sys
import os
import os.path
import re
import argparse
import pprint
import glob
from collections import OrderedDict
import socket
import urllib
import copy
import shutil
import ConfigParser

CONFIG_FILE_PATH = 'config_OpenROBO_utils.txt'
DEFAULT_SYNC_PORT = 49999
DEFAULT_SOURCE_DIR = "./source"
DEFAULT_HEADER_DIR = "./header"

BUILD_DIR = './build/'

default_config = {
    'name': None,
    'source_dir': DEFAULT_SOURCE_DIR,
    'header_dir': DEFAULT_HEADER_DIR,
    'sync_TP_addr': None,
    'sync_TP_port': None
}


class SourceCodeSync:

    class ClientInfo:

        def __init__(self, sock, addr):
            self.sock = sock
            self.addr = addr

    def __init__(self, name, src_dir="./", header_dir="./"):
        self.name = name
        self.src_dir = src_dir
        self.header_dir = header_dir

    def recvString(self, sock):
        size = int(sock.recv(8), 16)
        if size == 0:
            return None, 0
        buf = sock.recv(size)
        return buf, size

    def recvToFile(self, sock, path):
        name, _ = self.recvString(sock)
        if name is None:
            return False
        size = int(sock.recv(8), 16)
        receivedSize = 0
        f = open(os.path.join(path, name), "w")
        while receivedSize != size:
            buf = sock.recv(size - receivedSize)
            f.write(buf)
            receivedSize += len(buf)
        f.close()
        print("received: %s" % (name))
        return True

    def sendFile(self, sock, path):
        self.sendString(sock, os.path.basename(path))
        size = os.path.getsize(path)
        sock.sendall("%08x" % (size))
        f = open(path, "r")
        sock.sendall(f.read(size))
        f.close()

    def sendString(self, sock, string):
        size = len(string)
        sock.sendall("%08x%s" % (size, string))

    def sendNone(slef, sock):
        size = 0
        sock.sendall("%08x" % (size))

    def client(self, host, port):
        client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        client.connect((host, port))
        self.sendString(client, self.name)
        self.recvString(client)
        commandCpp = os.path.join(self.src_dir, "%s_Command.cpp" % (self.name))
        commandH = os.path.join(self.header_dir, "%s_Command.h" % (self.name))
        self.sendFile(client, commandCpp)
        print("sent to TP: %s" % (commandCpp))
        self.sendFile(client, commandH)
        print("sent to TP: %s" % (commandH))

        prefix_prog = re.compile(r".*/(.+)_Command.cpp")
        for p in glob.glob(self.src_dir + "/*_Command.cpp"):
            m = prefix_prog.match(p)
            prefix = m.group(1)
            if prefix == self.name:
                continue
            self.sendString(client, prefix)
            self.recvToFile(client, self.src_dir)
            self.recvToFile(client, self.header_dir)

        self.sendNone(client)
        client.close()

    def acceptOnSever(self, port):
        client_dict = {}
        serversock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        serversock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        serversock.bind(('', port))
        serversock.listen(10)

        sys.stdout.write("How many subsystems? : ")
        sys.stdout.flush()
        num = int(raw_input())
        for _ in xrange(num):
            sys.stdout.write("wait to accept... ")
            sys.stdout.flush()
            clientsock, client_address = serversock.accept()
            clientname, _ = self.recvString(clientsock)
            client_dict[clientname] = self.ClientInfo(clientsock, client_address)
            sys.stdout.write("accepted %s\n" % (clientname))
        serversock.close()

        return client_dict

    def server(self, port):
        client_dict = self.acceptOnSever(port)
        for c in client_dict.values():
            self.sendNone(c.sock)
            self.recvToFile(c.sock, self.src_dir)
            self.recvToFile(c.sock, self.header_dir)
        for name, c in client_dict.items():
            while True:
                prefix, _ = self.recvString(c.sock)
                if prefix is None:
                    break
                commandCpp = os.path.join(self.src_dir, "%s_Command.cpp" % (prefix))
                commandH = os.path.join(self.header_dir, "%s_Command.h" % (prefix))
                self.sendFile(c.sock, commandCpp)
                print("sent to %s: %s" % (name, commandCpp))
                self.sendFile(c.sock, commandH)
                print("sent to %s: %s" % (name, commandCpp))
            c.sock.close()


class CsubthreadinittermTermParser:

    def __init__(self):
        self.subthread_infos = []
        self.init_infos = []
        self.term_infos = []

    def __repr__(self):
        return "Subthread %s / init %s / term %s" % (repr(self.subthread_infos), repr(self.init_infos), repr(self.term_infos))

    def parseFunctionPrototype(self, line):
        # $1:returnType $2:funcName $3:args
        func_prog = re.compile(r"\s*(\S+)\s+([^\s(]+)\s*\(([^)]*)\s*\)")
        m = func_prog.match(line)
        if not m:
            return None

        return m.group(2)

    def parseFromFile(self, path):
        doxgen_start_prog = re.compile(r"/[*][*!]")
        doxgen_end_prog = re.compile(r"[*]/")
        targets = [{'prog': re.compile(r"[*]\s*Subthread@OpenROBO", re.IGNORECASE), 'infos': self.subthread_infos}, {'prog': re.compile(r"[*]\s*init@OpenROBO", re.IGNORECASE), 'infos': self.init_infos}, {'prog': re.compile(r"[*]\s*term@OpenROBO", re.IGNORECASE), 'infos': self.term_infos}]
        f = open(path, 'r')
        doxygen_flag = False
        parsing_flag = False
        ret = False
        infos = None
        for line in f:
            if not doxygen_flag:
                if parsing_flag:
                    name = self.parseFunctionPrototype(line)
                    if name is not None:
                        infos.append(name)
                        parsing_flag = False
                        ret = True
                elif doxgen_start_prog.search(line):
                    doxygen_flag = True
                continue
            if doxgen_end_prog.search(line):
                doxygen_flag = False
                continue
            if not parsing_flag:
                for t in targets:
                    if t['prog'].search(line):
                        infos = t['infos']
                        parsing_flag = True
                        break
                continue

        f.close()

        return ret


class CStructParser:

    class StructInfo:

        def __init__(self):
            self.name = ""
            self.ele_dict = OrderedDict()

        def __repr__(self):
            return "struct '%s' {%s}" % (self.name, repr(self.ele_dict))

        class ElementInfo:

            def __init__(self):
                self.full_type = ""
                self.type = ""
                self.is_array = False
                self.array_num = 0

            def __repr__(self):
                return """<full_type: "%s", type: "%s", is_array: %s, array_num: %d>""" % (self.full_type, self.type, self.is_array, self.array_num)

    def __init__(self):
        self.infos = []

    def parseArrayIndex(self, name):
        n = 1

        is_array = True

        array_prog = re.compile(r"([^\[\]]+)((\[[0-9]+\])+)")
        array_index_prog = re.compile(r"\[([0-9]+)\]")
        m = array_prog.search(name)
        if not m:
            is_array = False
            return name, n, is_array

        name = m.group(1)
        index_str = m.group(2)
        for m in array_index_prog.finditer(index_str):
            n *= int(m.group(1))

        return name, n, is_array

    def parseStructName(self, line):
        struct_prog = re.compile(r"\s*struct\s+([^ {\n]+).*")
        m = struct_prog.match(line)
        if not m:
            return False, None

        return True, m.group(1)

    def parseStruct(self, line, info):
        pointer_prog = re.compile(r"[*]")
        end_struct_prog = re.compile(r"}")
        variable_prog = re.compile(r"\s*?((\S+[ *]+)+)(\S+?)\s*?;")
        type_prog = re.compile(r"([^ *]+)[ *]*$")

        if pointer_prog.search(line):
            raise Exception('element of struct has pointer : "%s"' % line)
            return False

        if end_struct_prog.search(line):
            return True

        m = variable_prog.match(line)
        if not m:
            return False

        full_type = m.group(1).strip()
        name = m.group(3)
        name, array_num, is_array = self.parseArrayIndex(name)

        _type = full_type
        m = type_prog.search(full_type)
        if m:
            _type = m.group(1)

        info.ele_dict[name] = self.StructInfo.ElementInfo()
        info.ele_dict[name].full_type = full_type
        info.ele_dict[name].array_num = array_num
        info.ele_dict[name].is_array = is_array
        info.ele_dict[name].type = _type

        return False

    def parseFromFile(self, path):
        doxygen_start_prog = re.compile(r"/[*][*!]")
        doxygen_end_prog = re.compile(r"[*]/")
        readwrite_prog = re.compile(r"[*]\s*ReadWrite@OpenROBO", re.IGNORECASE)
        f = open(path, 'r')
        doxygen_flag = False
        parsing_flag = False
        struct_flag = False
        info = None
        ret = False
        for line in f:
            if not doxygen_flag:
                if parsing_flag:
                    if struct_flag:
                        if self.parseStruct(line, info):
                            self.infos.append(info)
                            parsing_flag = False
                            struct_flag = False
                            ret = True
                    else:
                        struct_flag, info.name = self.parseStructName(line)
                    continue
                if doxygen_start_prog.search(line):
                    doxygen_flag = True
                continue
            if doxygen_end_prog.search(line):
                doxygen_flag = False
                continue
            if not parsing_flag:
                if readwrite_prog.search(line):
                    info = self.StructInfo()
                    parsing_flag = True
                continue

        f.close()

        return ret


class CPrototypeParser:

    class FunctionInfo:

        class ArgmentInfo:

            def __init__(self):
                self.full_type = ""
                self.type = ""
                self.is_array = False
                self.array_num = 0
                self.is_pointer = False
                self.is_in = False
                self.is_out = False

            def __repr__(self):
                return """<full_type: "%s", type: "%s", is_array: %s, array_num: %d, is_pointer: %s, is_in: %s, is_out: %s>""" % (self.full_type, self.type, self.is_array, self.array_num, self.is_pointer, self.is_in, self.is_out)

        def __init__(self):
            self.name = ""
            self.return_type = ""
            self.arg_dict = OrderedDict()

        def __repr__(self):
            return "%s %s(%s)" % (self.return_type, self.name, repr(self.arg_dict))

    def __init__(self):
        self.infos = []

    def parseArrayIndex(self, name):
        n = 1

        is_array = True

        array_prog = re.compile(r"([^\[\]]+)((\[[0-9]+\])+)")
        array_index_prog = re.compile(r"\[([0-9]+)\]")
        m = array_prog.search(name)
        if not m:
            is_array = False
            return name, n, is_array

        name = m.group(1)
        index_str = m.group(2)
        for m in array_index_prog.finditer(index_str):
            n *= int(m.group(1))

        return name, n, is_array

    def parseFunctionPrototype(self, line, info):
        # $1:returnType $2:funcName $3:args
        func_prog = re.compile(r"\s*(\S+)\s+([^\s(]+)\s*\(([^)]*)\s*\)")
        arg_split_prog = re.compile(r"(.+?)(,|$)")
        arg_prog = re.compile(r"\s*([^,]*[^ ,]+[ *,]+)(\S+?)\s*?$")
        type_prog = re.compile(r"([^ *]+)[ *]*$")
        pointer_prog = re.compile(r"[*]")
        m = func_prog.match(line)
        if not m:
            return False
        info.return_type = m.group(1)
        info.name = m.group(2)
        ite = arg_split_prog.finditer(m.group(3))
        for m in ite:
            m = arg_prog.match(m.group(1))
            if not m:
                continue
            name = m.group(2)

            name, num, is_array = self.parseArrayIndex(name)
            info.arg_dict[name].array_num = num
            info.arg_dict[name].is_array = is_array

            full_type = m.group(1).strip()
            info.arg_dict[name].full_type = full_type

            is_pointer = False
            if pointer_prog.search(full_type):
                is_pointer = True
            info.arg_dict[name].is_pointer = is_pointer

            m2 = type_prog.search(full_type)
            if not m2:
                continue
            _type = m2.group(1)
            info.arg_dict[name].type = _type

        return True

    def parseDoxgen(self, line, info):
        param_prog = re.compile(r"\s*[*]\s*@param\[(.+?)\]\s+([\S]+)")
        in_prog = re.compile(r"IN", re.IGNORECASE)
        out_prog = re.compile(r"OUT", re.IGNORECASE)
        m = param_prog.match(line)
        if not m:
            return False

        arg = self.FunctionInfo.ArgmentInfo()
        if in_prog.search(m.group(1)):
            arg.is_in = True
        else:
            arg.is_in = False
        if out_prog.search(m.group(1)):
            arg.is_out = True
        else:
            arg.is_out = False

        info.arg_dict[m.group(2)] = arg
        return True

    def parseFromFile(self, path):
        doxgen_start_prog = re.compile(r"/[*][*!]")
        doxgen_end_prog = re.compile(r"[*]/")
        msgfunc_prog = re.compile(r"[*]\s*MessageFunction@OpenROBO", re.IGNORECASE)
        f = open(path, 'r')
        start_flag = False
        parsing_flag = False
        info = None
        ret = False
        for line in f:
            if not start_flag:
                if parsing_flag:
                    if self.parseFunctionPrototype(line, info):
                        self.infos.append(info)
                        parsing_flag = False
                        ret = True
                elif doxgen_start_prog.search(line):
                    start_flag = True
                continue
            if doxgen_end_prog.search(line):
                start_flag = False
                continue
            if not parsing_flag:
                if msgfunc_prog.search(line):
                    info = self.FunctionInfo()
                    parsing_flag = True
                continue
            self.parseDoxgen(line, info)

        f.close()

        return ret


class SourceCodeGenerator:

    def __init__(self, name, func_infos, struct_infos, subthread_infos, init_infos, term_infos, include_headers, include_main_headers):
        self.name = name
        self.func_infos = func_infos
        self.subthread_infos = subthread_infos
        self.init_infos = init_infos
        self.term_infos = term_infos
        self.struct_infos = struct_infos
        self.headers = include_headers
        self.main_headers = include_main_headers

    def genMessageCVariableDeclaration(self, f, i):
        f.write('void Message_%s(const char* message)\n{\n' % (i.name))
        f.write('\tint res;\n')
        f.write('\tchar *returnMessage;\n')
        f.write('\n')
        for name, a in i.arg_dict.items():
            if a.type == "string" and a.is_pointer:
                f.write('\tconst char* _%s;\n' % (name))
            elif a.is_array:
                f.write('\t%s _%s[%d];\n' % (a.type, name, a.array_num))
            else:
                f.write('\t%s _%s;\n' % (a.type, name))

    def genMessageCGetParam(self, f, i):
        for name, a in i.arg_dict.items():
            if not a.is_in:
                continue
            if a.is_array:
                f.write('\tOpenROBO_Message_GetParam_%sArray(message, "%s", _%s, %d);\n' % (a.type, name, name, a.array_num))
            else:
                f.write('\tOpenROBO_Message_GetParam_%s(message, "%s", &_%s);\n' % (a.type, name, name))

    def genMessageCCallFunction(self, f, i):
        f.write('\tres = %s(' % (i.name))
        comma_str = ""
        for name, a in i.arg_dict.items():
            if a.type != "string" and a.is_pointer:
                f.write(comma_str + '&_%s' % (name))
            else:
                f.write(comma_str + "_%s" % (name))
            comma_str = ", "
        f.write(');\n')

    def genMessageCSetParam(self, f, i):
        f.write('\tOpenROBO_Message_GetBuffer(&returnMessage);\n')
        f.write('\tOpenROBO_Message_MakeReturnMessage(returnMessage, "%s");\n\n' % (i.name))
        for name, a in i.arg_dict.items():
            if not a.is_out:
                continue
            if a.is_array:
                f.write('\tOpenROBO_Message_SetParam_%sArray(returnMessage, "%s", _%s, %d);\n' % (a.type, name, name, a.array_num))
            else:
                f.write('\tOpenROBO_Message_SetParam_%s(returnMessage, "%s", &_%s);\n' % (a.type, name, name))
        f.write('\tOpenROBO_Message_SetReturnValue(returnMessage, res);\n')

    def genMessageC(self, path):
        f = open(path, 'w')

        f.write('#include "OpenROBO.h"\n\n')
        for h in self.headers:
            f.write('#include "%s"\n' % (h))
        f.write('\n')

        for i in self.func_infos:
            self.genMessageCVariableDeclaration(f, i)
            f.write('\n')
            self.genMessageCGetParam(f, i)
            f.write('\n')
            self.genMessageCCallFunction(f, i)
            f.write('\n')
            self.genMessageCSetParam(f, i)
            f.write('\n')
            f.write('\tOpenROBO_Socket_SendReturnMessage(returnMessage);\n')
            f.write('\n')
            for name, a in i.arg_dict.items():
                if not a.is_in:
                    continue
                if a.type == "string":
                    f.write('\tOpenROBO_Message_Free(%s);\n' % (name))

            f.write('}\n\n')
        f.close()

    def genMessageH(self, path):
        f = open(path, 'w')
        for i in self.func_infos:
            f.write("void Message_%s(const char* message);\n" % (i.name))
        f.close()

    def genCommandCReadWriteFunction(self, f):
        for i in self.struct_infos:
            self.genCommandCReadFunction(f, i)
            self.genCommandCWriteFunction(f, i)

    def genCommandCReadFunction(self, f, i):
        f.write('int %s_Read_%s(struct %s_%s *_%s)\n{\n' % (self.name, i.name, self.name, i.name, i.name))
        f.write('\tstatic double last_time = 0.0;\n')
        f.write('\tdouble time;\n')
        f.write('\tchar *message;\n')
        f.write('\tint res;\n')

        f.write('\n\tOpenROBO_Message_GetBuffer(&message);\n')
        f.write('\tOpenROBO_Message_MakeReadMessage(message, "%s");\n' % (i.name))
        f.write('\tOpenROBO_Socket_SendCommandMessage("%s", message);\n\n' % (self.name))

        f.write('\tres = OpenROBO_Socket_ReceiveReturnMessage("%s", &message);\n' % (self.name))
        f.write('\tif (res != OpenROBO_Return_Success) {\n')
        f.write('\t\treturn res;\n')
        f.write('\t}\n\n')

        f.write('\tOpenROBO_Message_GetReturnValue(message, &res);\n')
        f.write('\tif (res != OpenROBO_Return_Success) {\n')
        f.write('\t\treturn res;\n')
        f.write('\t}\n\n')

        f.write('\tOpenROBO_Message_GetTime(message, &time);\n')
        self.genCommandCStructGetParam(f, i)

        f.write('\n\tif (time > last_time) {\n')
        f.write('\t\tres = OpenROBO_Return_Success;\n')
        f.write('\t\tlast_time = time;\n')
        f.write('\t} else {\n')
        f.write('\t\tres = OpenROBO_Return_NotUpdated;\n')
        f.write('\t}\n\n')
        f.write('\treturn res;\n')
        f.write('}\n\n')

    def genCommandCWriteFunction(self, f, i):
        f.write('int %s_Write_%s(const struct %s_%s *_%s)\n{\n' % (self.name, i.name, self.name, i.name, i.name))
        f.write('\tchar *message;\n')
        f.write('\tint res;\n')

        f.write('\n\tOpenROBO_Message_GetBuffer(&message);\n')
        f.write('\tOpenROBO_Message_MakeWriteMessage(message, "%s");\n' % (i.name))
        self.genCommandCStructSetParam(f, i)

        f.write('\n\tOpenROBO_Socket_SendCommandMessage("%s", message);\n\n' % (self.name))

        f.write('\tres = OpenROBO_Socket_ReceiveReturnMessage("%s", &message);\n' % (self.name))
        f.write('\tif (res != OpenROBO_Return_Success) {\n')
        f.write('\t\treturn res;\n')
        f.write('\t}\n\n')

        f.write('\tOpenROBO_Message_GetReturnValue(message, &res);\n\n')

        f.write('\treturn res;\n')
        f.write('}\n\n')

    def genCommandC(self, path):
        f = open(path, 'w')
        f.write('#include "OpenROBO.h"\n\n')
        f.write('#include "%s_Command.h"\n\n' % (self.name))
        for i in self.func_infos:
            is_output_static = False
            for name, a in i.arg_dict.items():
                if not a.is_out:
                    continue
                if a.is_array:
                    f.write('static %s *%s_%s;\n' % (a.full_type, i.name, name))
                else:
                    f.write('static %s %s_%s;\n' % (a.full_type, i.name, name))
                is_output_static = True
            if is_output_static:
                f.write("\n")
            self.genCommandCStartFunction(f, i)
            self.genCommandCStopFunction(f, i)
            self.genCommandCWaitFunction(f, i)
            self.genCommandCCallFunction(f, i)

        self.genCommandCReadWriteFunction(f)
        f.close()

    def genCommandCCallFunction(self, f, i):
        f.write('int %s_%s(%s)\n{\n' % (self.name, i.name, self.getCommandArgments(i)))
        f.write('\tint res;\n')
        f.write('\tres = %s_Start_%s(' % (self.name, i.name))
        comma_str = ""
        for name in i.arg_dict.keys():
            f.write(comma_str + "_%s" % (name))
            comma_str = ", "
        f.write(');\n')
        f.write('\tif (res != OpenROBO_Return_Success) {\n')
        f.write('\t\treturn res;\n')
        f.write('\t}\n\n')
        f.write('\tres = %s_Wait_%s();\n' % (self.name, i.name))
        f.write('\tif (res != OpenROBO_Return_Success) {\n')
        f.write('\t\treturn res;\n')
        f.write('\t}\n\n')
        f.write('\treturn OpenROBO_Return_Success;\n}\n\n')

    def genCommandCStartFunction(self, f, i):
        f.write('int %s_Start_%s(%s)\n{\n' % (self.name, i.name, self.getCommandArgments(i)))
        f.write('\tint res;\n')
        f.write('\tchar *message;\n')

        f.write('\n\tOpenROBO_Message_GetBuffer(&message);\n')
        f.write('\tOpenROBO_Message_MakeOperationMessage(message, "%s");\n\n' % (i.name))

        for name, a in i.arg_dict.items():
            if not a.is_in:
                continue
            if a.is_array:
                f.write('\tOpenROBO_Message_SetParam_%sArray(message, "%s", _%s, %d);\n' % (a.type, name, name, a.array_num))
            else:
                f.write('\tOpenROBO_Message_SetParam_%s(message, "%s", &_%s);\n' % (a.type, name, name))

        f.write('\n\tres = OpenROBO_Socket_SendCommandMessage("%s", message);\n' % (self.name))
        f.write('\tif (res != OpenROBO_Return_Success) {\n')
        f.write('\t\treturn res;\n')
        f.write('\t}\n\n')

        f.write('\tres = OpenROBO_Socket_ReceiveReturnMessage("%s", &message);\n' % (self.name))
        f.write('\tif (res != OpenROBO_Return_Success) {\n')
        f.write('\t\treturn res;\n')
        f.write('\t}\n\n')

        f.write('\tOpenROBO_Message_GetReturnValue(message, &res);\n')

        for name, a in i.arg_dict.items():
            if not a.is_out:
                continue
            f.write('\t%s_%s = _%s;\n' % (i.name, name, name))

        f.write('\n\treturn res;\n}\n\n')

    def genCommandCGetParam(self, f, i):
        for name, a in i.arg_dict.items():
            if not a.is_out:
                continue
            if a.is_array:
                f.write('\tOpenROBO_Message_GetParam_%sArray(message, "%s", %s_%s, %d);\n' % (a.type, name, i.name, name, a.array_num))
            else:
                f.write('\tOpenROBO_Message_GetParam_%s(message, "%s", %s_%s);\n' % (a.type, name, i.name, name))

    def genCommandCStructSetParam(self, f, i):
        for name, e in i.ele_dict.items():
            if e.is_array:
                f.write('\tOpenROBO_Message_SetParam_%sArray(message, "%s", _%s->%s, %d);\n' % (e.type, name, i.name, name, e.array_num))
            else:
                f.write('\tOpenROBO_Message_SetParam_%s(message, "%s", &_%s->%s);\n' % (e.type, name, i.name, name))

    def genCommandCStructGetParam(self, f, i):
        for name, e in i.ele_dict.items():
            if e.is_array:
                f.write('\tOpenROBO_Message_GetParam_%sArray(message, "%s", _%s->%s, %d);\n' % (e.type, name, i.name, name, e.array_num))
            else:
                f.write('\tOpenROBO_Message_GetParam_%s(message, "%s", &_%s->%s);\n' % (e.type, name, i.name, name))

    def genCommandCStopFunction(self, f, i):
        f.write('int %s_Stop_%s()\n{\n' % (self.name, i.name))
        f.write('\tchar *message;\n')
        f.write('\n\tOpenROBO_Message_GetBuffer(&message);\n')
        f.write('\tOpenROBO_Message_MakeStopMessage(message, "%s");\n' % (i.name))
        f.write('\tOpenROBO_Socket_SendCommandMessage("%s", message);\n\n' % (self.name))
        f.write('\treturn %s_Wait_%s();\n}\n\n' % (self.name, i.name))

    def genCommandCWaitFunction(self, f, i):
        f.write('int %s_Wait_%s()\n{\n' % (self.name, i.name))
        f.write('\tchar *message;\n')
        f.write('\tint res;\n')
        f.write('\n\tOpenROBO_Message_GetBuffer(&message);\n')
        f.write('\tOpenROBO_Message_MakeWaitMessage(message, "%s");\n' % (i.name))
        f.write('\tOpenROBO_Socket_SendCommandMessage("%s", message);\n\n' % (self.name))
        f.write('\tres = OpenROBO_Socket_ReceiveReturnMessage("%s", &message);\n' % (self.name))
        f.write('\tif (res != OpenROBO_Return_Success) {\n')
        f.write('\t\treturn res;\n')
        f.write('\t}\n\n')
        f.write('\tOpenROBO_Message_GetReturnValue(message, &res);\n\n')
        self.genCommandCGetParam(f, i)
        f.write('\n\treturn res;\n}\n\n')

    def getCommandArgments(self, i):
        ret_str = ""
        comma_str = ""
        for name, a in i.arg_dict.items():
            if a.is_array:
                ret_str += comma_str + '%s _%s[%d]' % (a.full_type, name, a.array_num)
            else:
                ret_str += comma_str + '%s _%s' % (a.full_type, name)
            comma_str = ", "
        return ret_str

    def genCommandHReadWrite(self, f):
        for i in self.struct_infos:
            f.write('struct %s_%s {\n' % (self.name, i.name))
            for name, e in i.ele_dict.items():
                if e.is_array:
                    f.write('\t%s %s[%d];\n' % (e.full_type, name, e.array_num))
                else:
                    f.write('\t%s %s;\n' % (e.full_type, name))
            f.write('};\n')
            f.write('int %s_Read_%s(struct %s_%s *_%s);\n' % (self.name, i.name, self.name, i.name, i.name))
            f.write('int %s_Write_%s(const struct %s_%s *_%s);\n' % (self.name, i.name, self.name, i.name, i.name))
            f.write('\n')

    def genCommandH(self, path):
        f = open(path, 'w')
        for i in self.func_infos:
            f.write('int %s_%s(%s);\n' % (self.name, i.name, self.getCommandArgments(i)))
            f.write('int %s_Start_%s(%s);\n' % (self.name, i.name, self.getCommandArgments(i)))
            f.write('int %s_Stop_%s();\n' % (self.name, i.name))
            f.write('int %s_Wait_%s();\n' % (self.name, i.name))
            f.write('\n')
        self.genCommandHReadWrite(f)
        f.close()

    def genMainH(self, path):
        if os.path.exists(path):
            return
        f = open(path, 'w')
        if self.name != "TP":
            f.write('#define TASKPLANNER_ADDRESS "192.168.0.200"\n')
        f.write('#define TASKPLANNER_PORT 50001\n')
        if self.name == "TP":
            f.write('\nstatic const char* const subsystemList[] = {\n\t"HRI",\n\t"AC",\n\t"TC",\n\t"VC",\n\t"VS",\n\t"CG",\n\tNULL\n};\n')
        f.close()

    def genMainC(self, path):
        f = open(path, 'w')
        f.write('#include <stdio.h>\n')
        f.write('#include "%s_Main.h"\n' % (self.name))
        f.write('#include "OpenROBO.h"\n')
        f.write('#include "%s_Message.h"\n\n' % (self.name))
        for h in self.main_headers:
            f.write('#include "%s"\n' % (h))
        f.write('\n')
        f.write('int main(int argc, char *argv[])\n{\n')
        f.write('\tint res;\n')
        f.write('\tres = OpenROBO_StartupMainThread("%s");\n' % (self.name))
        f.write('\tif (res != OpenROBO_Return_Success) {\n')
        f.write('\t\tfprintf(stderr, "error: startup\\n");\n')
        f.write('\t\treturn res;\n')
        f.write('\t}\n')
        if self.name == "TP":
            f.write('\tres = OpenROBO_Socket_AcceptConnection(TASKPLANNER_PORT, subsystemList);\n')
        else:
            f.write('\tres = OpenROBO_Socket_MakeConnection(TASKPLANNER_ADDRESS, TASKPLANNER_PORT);\n')
        f.write('\tif (res != OpenROBO_Return_Success) {\n')
        f.write('\t\tfprintf(stderr, "error: make connection\\n");\n')
        f.write('\t\treturn res;\n')
        f.write('\t}\n\n')
        for i in self.subthread_infos:
            f.write('\tres = OpenROBO_Thread_CreateSubthread(%s, "%s", argc, argv);\n' % (i, i))
            f.write('\tif (res != OpenROBO_Return_Success) {\n')
            f.write('\t\tfprintf(stderr, "error: create subthread \\"%s\\"\\n");\n' % (i))
            f.write('\t\treturn res;\n')
            f.write('\t}\n')
        f.write('\n\tOpenROBO_MessageFunctionEntry_t messageFunctionEntry[] = {\n')
        for i in self.func_infos:
            f.write('\t\t{Message_%s, "%s"},\n' % (i.name, i.name))
        f.write('\t\tOPENROBO_END_OF_MESSAGE_FUNCTION_ENTRY\n\t};\n')

        f.write('\n\tres = OpenROBO_Main(messageFunctionEntry);\n\n')

        for i in self.term_infos:
            f.write('\t%s();\n' % (i))
        f.write('\n\treturn res;\n}')
        f.close()


def update_main(args):
    src_dir = args.src_dir
    header_dir = args.header_dir
    src_list = ["https://raw.githubusercontent.com/r01hee/SocketCom/master/SocketCom.cpp", "https://raw.githubusercontent.com/OpenROBO/OpenROBO/master/source/OpenROBO.cpp"]
    header_list = ["https://raw.githubusercontent.com/r01hee/SocketCom/master/SocketCom.h", "https://raw.githubusercontent.com/OpenROBO/OpenROBO/master/header/OpenROBO.h"]
    others = ["https://raw.githubusercontent.com/r01hee/OpenROBO_utils/master/OpenROBO_utils.py", "https://raw.githubusercontent.com/OpenROBO/OpenROBO/master/OpenROBO.mak"]
    for s in src_list:
        basepath = os.path.basename(s)
        path = os.path.join(src_dir, basepath)
        print("update %s" % (basepath))
        urllib.urlretrieve(s, path)
    for h in header_list:
        basepath = os.path.basename(h)
        path = os.path.join(header_dir, basepath)
        print("update %s" % (basepath))
        urllib.urlretrieve(h, path)
    for o in others:
        basepath = os.path.basename(o)
        path = basepath
        print("update %s" % (basepath))
        urllib.urlretrieve(o, path)


def setup_main(args):
    config = copy.deepcopy(default_config)
    sys.stdout.write("Subsystem name(such as TP,HRI,AC)?: ")
    sys.stdout.flush()
    config['name'] = raw_input()
    sys.stdout.write("TP address(such as 192.168.0.200)? : ")
    config['sync_TP_addr'] = raw_input()
    config['sync_TP_port'] = str(DEFAULT_SYNC_PORT)
    f = open(CONFIG_FILE_PATH, 'w')
    f.write('[DEFAULT]\n')
    f.write('name = %s\n' % (config['name']))
    f.write('source_dir = %s\n' % (config['source_dir']))
    f.write('header_dir = %s\n' % (config['header_dir']))
    f.write('sync_TP_addr = %s\n' % (config['sync_TP_addr']))
    f.write('sync_TP_port = %s\n' % (config['sync_TP_port']))
    f.close()
    try:
        os.mkdir(config['source_dir'])
    except OSError:
        pass
    try:
        os.mkdir(config['header_dir'])
    except OSError:
        pass
    update_main(args)

def clean_main(args):
    print('remove %s' % (BUILD_DIR))
    if os.path.exists(BUILD_DIR):
        shutil.rmtree(BUILD_DIR)


def sync_main(args):
    src_dir = args.src_dir
    header_dir = args.header_dir
    s = SourceCodeSync(args.name, src_dir, header_dir)
    port = int(args.port)
    if args.name == "TP":
        s.server(port)
    else:
        if not args.addr:
            print("error: argument -a/--addr is required")
            exit(2)
        s.client(args.addr, port)


def gen_main(args):
    headers = args.header
    if not headers:
        headers = glob.glob(args.header_dir + "/*.h")

    include_headers = []
    include_main_headers = []

    c = CPrototypeParser()
    for h in headers:
        if c.parseFromFile(h):
            include_headers.append(h)
    if not args.quiet:
        pprint.pprint(c.infos)

    s = CStructParser()
    for h in headers:
        s.parseFromFile(h)
    if not args.quiet:
        pprint.pprint(s.infos)

    subthreadinitterm = CsubthreadinittermTermParser()
    for h in headers:
        if subthreadinitterm.parseFromFile(h):
            include_main_headers.append(h)
    if not args.quiet:
        pprint.pprint(subthreadinitterm)

    include_headers = [os.path.basename(h) for h in include_headers]
    if args.include_prefix:
        include_headers = [os.path.join(args.include_prefix, h) for h in include_headers]
    include_main_headers = [os.path.basename(h) for h in include_main_headers]
    if args.include_prefix:
        include_main_headers = [os.path.join(args.include_prefix, h) for h in include_main_headers]
    if not args.quiet:
        pprint.pprint(include_headers)
        pprint.pprint(include_main_headers)

    gen = SourceCodeGenerator(name=args.name, func_infos=c.infos, struct_infos=s.infos, subthread_infos=subthreadinitterm.subthread_infos, init_infos=subthreadinitterm.init_infos, term_infos=subthreadinitterm.term_infos, include_headers=include_headers, include_main_headers=include_main_headers)
    out_src_dir = args.out_src_dir
    out_header_dir = args.out_header_dir
    gen.genCommandC(os.path.join(out_src_dir, "%s_Command.cpp" % (args.name)))
    gen.genCommandH(os.path.join(out_header_dir, "%s_Command.h" % (args.name)))
    gen.genMessageC(os.path.join(out_src_dir, "%s_Message.cpp" % (args.name)))
    gen.genMessageH(os.path.join(out_header_dir, "%s_Message.h" % (args.name)))
    gen.genMainC(os.path.join(out_src_dir, "%s_Main.cpp" % (args.name)))
    gen.genMainH(os.path.join(out_header_dir, "%s_Main.h" % (args.name)))


def main():
    name_required = True
    config = ConfigParser.SafeConfigParser(default_config)
    config.read(CONFIG_FILE_PATH)
    if config.get('DEFAULT', 'name') is not None:
        name_required = False

    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers()

    parser.add_argument('-v', '--version', action='version', version='%(prog)s ver.1.0.0')

    parser_gen = subparsers.add_parser('gen', help="Generate Source Code such as XX_Main.cpp, XX_Message.[cpp|h], XX_Command.[cpp|h]")
    parser_gen.add_argument('-n', '--name', required=name_required, help="Subsystem Name(Short-Name) such as TP,HRI,AC", default=config.get('DEFAULT', 'name'))
    parser_gen.add_argument('-q', '--quiet', action='store_true', help='quiet (no output)')
    group = parser_gen.add_mutually_exclusive_group()
    group.add_argument('--header-dir', type=str, help="directory includes headers(*.h)", default=config.get('DEFAULT', 'header_dir'))
    group.add_argument('--header', nargs='+', help="headers(*.h)")
    parser_gen.add_argument('--include-prefix', help='prefix of #include header; include dir, such as "include/"')
    parser_gen.add_argument('--out-src-dir', help='directory to output source code(*.cpp)', default=config.get('DEFAULT', 'source_dir'))
    parser_gen.add_argument('--out-header-dir', help='directory to output header(*.h)', default=config.get('DEFAULT', 'header_dir'))
    parser_gen.set_defaults(func=gen_main)

    sync_addr_required = True if config.get('DEFAULT', 'sync_TP_addr') is None else False
    sync_port_required = True if config.get('DEFAULT', 'sync_TP_port') is None else False
    parser_sync = subparsers.add_parser('sync', help="Sync Source Codes between Subsystem")
    parser_sync.add_argument('-n', '--name', required=name_required, help="Subsystem Name(Short-Name) such as TP,HRI,AC", default=config.get('DEFAULT', 'name'))
    parser_sync.add_argument('-a', '--addr', required=sync_addr_required, help="address", default=config.get('DEFAULT', 'sync_TP_addr'))
    parser_sync.add_argument('-p', '--port', required=sync_port_required, help="port", default=config.get('DEFAULT', 'sync_TP_port'))
    parser_sync.add_argument('--src-dir', help='directory to output source code(*.cpp)', default=config.get('DEFAULT', 'source_dir'))
    parser_sync.add_argument('--header-dir', help='directory to output header(*.h)', default=config.get('DEFAULT', 'header_dir'))
    parser_sync.set_defaults(func=sync_main)

    parser_update = subparsers.add_parser('update', help="update OpenROBO_utils.py and OpenROBO.[cpp|h] and SocketCom.[cpp|h]")
    parser_update.add_argument('--src-dir', help='directory to output source code(*.cpp)', default=config.get('DEFAULT', 'source_dir'))
    parser_update.add_argument('--header-dir', help='directory to output header(*.h)', default=config.get('DEFAULT', 'header_dir'))
    parser_update.set_defaults(func=update_main)

    parser_setup = subparsers.add_parser('setup', help="set up default template set")
    parser_setup.add_argument('--src-dir', help='directory to output source code(*.cpp)', default=config.get('DEFAULT', 'source_dir'))
    parser_setup.add_argument('--header-dir', help='directory to output header(*.h)', default=config.get('DEFAULT', 'header_dir'))
    parser_setup.set_defaults(func=setup_main)

    parser_clean = subparsers.add_parser('clean', help="clean temporary files; same as 'make clean'")
    parser_clean.set_defaults(func=clean_main)

    args = parser.parse_args()
    args.func(args)


if __name__ == '__main__':
    main()
