from scout.server import main
from scout.server import parse_options


if __name__ == '__main__':
    app = parse_options()
    main(app)
