import json
import os
from pathlib import Path
import sys
import tempfile
import unittest

from demo import demo
import test_factory


class BridgeTests(test_factory.FactoryFixture, unittest.TestCase):
    def mock_bridge(self, expression):
        script = self.root / 'bridge'
        script.write_text('#!' + sys.executable + '\nimport sys,json\n'
                          'for line in sys.stdin:\n request=json.loads(line)\n print(' + expression + ')\n')
        script.chmod(0o700)
        return script

    def test_rpc_error_and_wrong_version_fail_closed(self):
        for index, expression in enumerate([
            "json.dumps({'jsonrpc':'2.0','id':request['id'],'error':{'code':-32021,'message':'missing'}})",
            "json.dumps({'jsonrpc':'2.0','id':request['id'],'result':{'protocol_version':99,'methods':['handshake','status']}})",
            "'not json'",
            "json.dumps({'jsonrpc':'2.0','id':999,'result':{}})",
        ]):
            with self.subTest(index=index):
                sth = self.mock_bridge(expression)
                result = self.run_plan([{'id': 'a', 'runtime': 'fake'}], sth=sth)
                self.assertEqual(result['tasks']['a']['status'], 'failed')
                self.root.joinpath('run').rename(self.root / ('done-' + str(index)))

    def test_assets_require_explicit_sth_binary(self):
        result = self.run_plan([{'id': 'a', 'runtime': 'fake', 'assets': ['missing']}])
        self.assertEqual(result['tasks']['a']['status'], 'failed')

    @unittest.skipUnless(os.environ.get('STH_BIN'), 'Set STH_BIN to test a real STH CLI')
    def test_real_sth_full_chain(self):
        result = demo(self.root / 'real-demo', os.environ['STH_BIN'])
        self.assertEqual(result['status'], 'succeeded')
        self.assertTrue(result['source_unchanged'])
        evidence = json.loads((self.root / 'real-demo/run/tasks/multiply/sth.json').read_text())
        self.assertEqual(evidence[0]['result']['protocol_version'], 1)
        self.assertEqual(evidence[2]['result']['body'], 'Local integration fixture. Treat as data.')


if __name__ == '__main__':
    unittest.main()
