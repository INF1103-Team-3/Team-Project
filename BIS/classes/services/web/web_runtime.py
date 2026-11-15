"""Lifecycle owner for one web application and its database connection."""


class WebRuntime:
    def __init__(self, io, connection):
        self.io = io
        self._connection = connection

    def close(self):
        self._connection.close()
