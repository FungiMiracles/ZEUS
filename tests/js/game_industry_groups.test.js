'use strict';
const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm'),path=require('node:path');
const context={window:{}};vm.createContext(context);vm.runInContext(fs.readFileSync(path.join(__dirname,'../../static/js/game_industry_view.js'),'utf8'),context);
const groups=(objects,kind)=>JSON.parse(JSON.stringify(context.window.GameIndustryView.groupObjects(objects,kind)));
test('mines group by resource and sum active output and total capacity separately',()=>{
 const result=groups([{category:'mine',kind:'coal',dailyExtraction:3,effectiveDailyExtraction:3},{category:'mine',kind:'coal',dailyExtraction:5,effectiveDailyExtraction:0},{category:'mine',kind:'oil',dailyExtraction:1,effectiveDailyExtraction:1}], 'mine');
 assert.equal(result.length,2);assert.equal(result[0].count,2);assert.equal(result[0].dailyExtraction,3);assert.equal(result[0].extractionCapacity,8);
});
test('power excludes offline plants from current totals while retaining all objects',()=>{
 const result=groups([{category:'power',kind:'coal',dailyProduction:100,effectiveDailyProduction:100},{category:'power',kind:'coal',dailyProduction:200,effectiveDailyProduction:0},{category:'mine',kind:'coal',dailyExtraction:1}], 'power');
 assert.equal(result.length,1);assert.equal(result[0].count,2);assert.equal(result[0].dailyProduction,100);assert.equal(result[0].productionCapacity,300);
});
test('factory types stay in one card but distinct products and periods are never mixed',()=>{
 const result=groups([{category:'factory',kind:'chips',product:'simple',days:1,quantity:10,effectiveQuantity:10},{category:'factory',kind:'chips',product:'simple',days:1,quantity:10,effectiveQuantity:0},{category:'factory',kind:'chips',product:'kerbit',days:1,quantity:6,effectiveQuantity:6},{category:'factory',kind:'tanks',product:'tanks',days:7,quantity:1,effectiveQuantity:1},{category:'factory',kind:'shipyard',product:'warships',days:'month',quantity:1,effectiveQuantity:1}], 'factory');
 assert.equal(result.length,3);assert.equal(result[0].count,3);assert.deepEqual(result[0].products,[{code:'simple',days:1,quantity:10,capacity:20},{code:'kerbit',days:1,quantity:6,capacity:6}]);assert.equal(result[1].products[0].days,7);assert.equal(result[2].products[0].days,'month');
});
