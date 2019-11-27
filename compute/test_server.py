from unittest import TestCase
from compute.Server import Server


class TestServer(TestCase):

    def test_get_user_data(self):
        content = {'type': 'bastion', 'private': 'private_key'}
        result = Server.get_user_data(content)
        expected = '#!/bin/bash' '\n' 'echo private_key > bastion.pem'
        self.assertEqual(expected, result)

