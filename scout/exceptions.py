from flask import jsonify


class InvalidSearchException(ValueError): pass


class InvalidRequestException(Exception):
    def __init__(self, error_message, code=None):
        self.error_message = error_message
        self.code = code or 400

    def response(self):
        return jsonify({'error': self.error_message}), self.code


def error(message, code=None):
    """
    Trigger an Exception that will short-circuit the Response cycle and return
    a 400 "Bad request" with the given error message.
    """
    raise InvalidRequestException(message, code=code)
