'use strict';
const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const source=fs.readFileSync(path.join(__dirname,'../../static/js/game_loans.js'),'utf8');
const context=vm.createContext({window:{}});vm.runInContext(fs.readFileSync(path.join(__dirname,'../../static/js/game_money.js'),'utf8'),context);vm.runInContext(source.slice(source.indexOf('const cents='),source.indexOf('async function post')),context);
test('loan display uses one decimal BLN beyond the Number safe integer range',()=>{const formatted=vm.runInContext("amount('9007199254740993.27')",context).replace(/[\s\u00a0\u202f]/g,'');assert.equal(formatted,'9007,2BLNROI');});
test('loan funding compares exact cents, including short decimal inputs',()=>{assert.equal(vm.runInContext("cents('10.1')",context),1010n);assert.equal(vm.runInContext("cents('0.01')",context),1n);assert.equal(vm.runInContext("cents('100.00') < cents('100.01')",context),true);});
