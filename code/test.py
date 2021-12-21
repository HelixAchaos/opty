import email
import random, csv, email.charset
from random import randrange
from email.generator import Generator


foo = [1, 2, 3, 4, 5, 6, 7]

"""random.randint(0, a) -> random.randrange(a + 1)"""
random.randint(0, 23)  # random.randrange(24)
random.randint(0, len(foo))  # random.randrange(len(foo) + 1)
random.randint(0, len(foo) - 1)  # random.randrange(len(foo))
random.randint(3, len(foo) - 1)  # random.randrange(3, len(foo)). unchanged

