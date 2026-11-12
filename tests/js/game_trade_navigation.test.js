'use strict';
const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const context={window:{}};vm.createContext(context);vm.runInContext(fs.readFileSync('static/js/game_trade_navigation.js','utf8'),context);
const start=Date.parse('3000-01-01T00:00:00Z'),ship={route:[[0,0],[10,0],[10,30]],startsAt:'3000-01-01T00:00:00Z',arrivesAt:'3000-01-01T04:00:00Z'};
test('merchant position follows distance along the water route',()=>{assert.deepEqual(Array.from(context.window.GameTradeNavigation.position(ship,start+2*3600000)),[10,10]);});
test('merchant stays at departure before start and at arrival after completion',()=>{assert.deepEqual(Array.from(context.window.GameTradeNavigation.position(ship,start-1000)),[0,0]);assert.deepEqual(Array.from(context.window.GameTradeNavigation.position(ship,start+10*3600000)),[10,30]);});
