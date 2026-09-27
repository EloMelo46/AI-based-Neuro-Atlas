"""Appearance tool schema, validation and acknowledged API roundtrip; no live calls."""
import json
import os
import unittest
from unittest.mock import patch
from main.brain_assistant import tools_for, validate_action, focus_result_error
from main.brain_viewer import app

class AppearanceToolTests(unittest.TestCase):
    def test_only_three_explicit_styles_are_advertised(self):
        definition=next(t for t in tools_for([]) if t['name']=='set_appearance')
        self.assertTrue(definition['strict'])
        self.assertEqual(definition['parameters']['required'],['appearance'])
        self.assertFalse(definition['parameters']['additionalProperties'])
        self.assertEqual(set(definition['parameters']['properties']['appearance']['enum']),{'learning','natural','digital'})

    def test_accepts_styles_rejects_unknown_types_and_extra_parameters(self):
        for style in ('learning','natural','digital'):
            self.assertEqual(validate_action('set_appearance',{'appearance':style},[])['arguments']['appearance'],style)
        for args in ({},None,{'appearance':'unknown'},{'appearance':None},{'appearance':[]},
                     {'appearance':True},{'appearance':{'natural':True}}, {'appearance':'natural','code':'x'}):
            with self.subTest(args=args), self.assertRaises(ValueError):
                validate_action('set_appearance',args,[])

    def test_wrong_or_missing_design_is_not_acknowledged(self):
        action=validate_action('set_appearance',{'appearance':'natural'},[])
        self.assertEqual(focus_result_error(action,{'appearance':'natural'}),'')
        self.assertTrue(focus_result_error(action,{'appearance':'learning'}))
        self.assertTrue(focus_result_error(action,{}))

    def test_acknowledged_tool_roundtrip(self):
        state={'loaded':[],'visible':[],'highlighted':[],'opacities':{},'cuts':{a:[0,100] for a in 'xyz'},'appearance':'learning'}
        for style in ('natural','digital','learning'):
            client=app.test_client(); outputs=[]
            def api(payload,*_):
                definition=next(t for t in payload['tools'] if t.get('name')=='set_appearance')
                self.assertIn(style,definition['parameters']['properties']['appearance']['enum'])
                results=[i for i in payload['input'] if i.get('type')=='function_call_output']
                if not results:
                    output=[{'type':'function_call','call_id':'design','name':'set_appearance','arguments':json.dumps({'appearance':style})}]
                else:
                    result=json.loads(results[-1]['output']); outputs.append(result)
                    output=[{'type':'message','content':[{'type':'output_text','text':'Design geändert.','annotations':[]}]}]
                yield {'type':'response.completed','response':{'status':'completed','output':output}}
            def post(body):
                response=client.post('/api/assistant/chat',headers={'X-Brain-Viewer':'1'},json=body)
                self.assertEqual(response.status_code,200)
                events=[json.loads(s) for s in response.get_data(as_text=True).splitlines()]
                self.assertFalse([e for e in events if e['type']=='error'],events)
                return next(e['data'] for e in events if e['type']=='result')
            with patch.dict(os.environ,{'OPENAI_API_KEY':'test-only'}), patch('main.brain_assistant.stream_openai',side_effect=api):
                first=post({'message':'Ändere das Design','state':state})
                self.assertEqual(first['actions'][0]['name'],'set_appearance')
                second=post({'turn_id':first['turn_id'],'state':{**state,'appearance':style},
                             'results':[{'call_id':'design','ok':True,'state':{**state,'appearance':style}}]})
                self.assertEqual(second['actions'],[])
                self.assertTrue(outputs[-1]['ok'])
                self.assertEqual(outputs[-1]['state']['appearance'],style)

if __name__=='__main__':unittest.main()
