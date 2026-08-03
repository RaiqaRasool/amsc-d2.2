# Web Error Handling

## Purpose

Keep internal exception details out of HTTP responses while retaining complete
tracebacks in server logs for developers and operators.

## Expected Behavior

- Unhandled web exceptions produce an HTTP 500 response with a generic page.
- The response does not contain exception messages, tracebacks, source code, or
  environment details.
- The original exception and traceback are written to the Flask server log.

## Development Behavior

Flask's interactive debugger takes precedence over the 500 handler while debug
mode is enabled. This is intentional for local development. Test the friendly
page with debug mode disabled before deployment.

## Key Components

- `app.py`: global HTTP 500 handler and server-side logging
- `templates/500.html`: user-safe error response

## Verification

- Run `python3 -m unittest discover -s tests -p 'test_web_error_handling.py'`.
