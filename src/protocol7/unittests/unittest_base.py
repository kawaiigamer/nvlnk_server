import logging
import unittest


class UnitTestsBase(unittest.TestCase):
    def setUp(self):
        logging.basicConfig(level=logging.DEBUG, datefmt="%d.%m.%y %H:%M:%S",
                            format=f'%(asctime)s[{self.__class__.__name__}][%(levelname)s] %(funcName)s:%(lineno)d %(message)s',
                            handlers=[logging.StreamHandler()])
        self.logger = logging.getLogger(self.__class__.__name__)
