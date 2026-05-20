#!/usr/bin/env python3
"""Test the NEXUS MCP server."""
import subprocess, json, sys

proc = subprocess.Popen(
    ['python3', '-m', 'nexus_mcp.server'],
    stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    text=True, cwd='/home/bozo/projects/orchestrator_work/nexus'
)

def send(req):
    proc.stdin.write(json.dumps(req) + '\n')
    proc.stdin.flush()
    line = proc.stdout.readline()
    return json.loads(line)

try:
    # Initialize
    init_resp = send({
        'jsonrpc': '2.0', 'id': 1, 'method': 'initialize',
        'params': {'protocolVersion': '2024-11-05', 'capabilities': {}, 'clientInfo': {'name': 'test', 'version': '1.0'}}
    })
    print('Init:', init_resp['result']['serverInfo'])
    
    # Send initialized notification
    proc.stdin.write(json.dumps({'jsonrpc': '2.0', 'method': 'notifications/initialized'}) + '\n')
    proc.stdin.flush()
    
    # List tools
    tools_resp = send({'jsonrpc': '2.0', 'id': 2, 'method': 'tools/list', 'params': {}})
    tools = tools_resp['result']['tools']
    print(f'\nTools ({len(tools)}):')
    for t in tools:
        print(f'  {t["name"]}: {t["description"][:70]}')
    
    # Test nexus_add_memory
    add_resp = send({
        'jsonrpc': '2.0', 'id': 3, 'method': 'tools/call',
        'params': {'name': 'nexus_add_memory', 'arguments': {'content': 'Test memory from MCP server', 'category': 'test', 'tags': 'mcp,test', 'emotional_weight': 0.8}}
    })
    print(f'\nAdd memory result:')
    print(add_resp['result']['content'])
    
    # Test nexus_search
    search_resp = send({
        'jsonrpc': '2.0', 'id': 4, 'method': 'tools/call',
        'params': {'name': 'nexus_search', 'arguments': {'query': 'test memory', 'limit': 5}}
    })
    print(f'\nSearch result:')
    print(search_resp['result']['content'])
    
    # Test nexus_stats
    stats_resp = send({
        'jsonrpc': '2.0', 'id': 5, 'method': 'tools/call',
        'params': {'name': 'nexus_stats', 'arguments': {}}
    })
    print(f'\nStats result:')
    print(stats_resp['result']['content'])
    
    # Test nexus_ask
    ask_resp = send({
        'jsonrpc': '2.0', 'id': 6, 'method': 'tools/call',
        'params': {'name': 'nexus_ask', 'arguments': {'question': 'What test memories do we have?'}}
    })
    print(f'\nAsk result:')
    print(ask_resp['result']['content'])
    
    print('\n=== ALL TESTS PASSED ===')
    
finally:
    proc.terminate()
