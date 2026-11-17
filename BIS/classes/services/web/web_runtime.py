"""Lifecycle owner for one web application and its database connection."""


class WebRuntime:
    def __init__(self, io, connection):
        self.__io = io
        self.__connection = connection

    @property
    def io(self):
        """Return the configured BIS boundary used by HTTP dependencies."""
        return self.__io

    def close(self):
        self.__connection.close()
