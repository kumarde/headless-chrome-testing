var Chrome = require('chrome-remote-interface');
var spawn = require('child_process').spawn;
var traceroute = require('traceroute');

if (process.argv[2] === undefined) {
  throw Error('No headless binary path provided.');
}

var headless = spawn(process.argv[2], [
  '--remote-debugging-port=9222']);

var screenshotUrl = process.argv[3] || 'https://paulirish.com';

// Dumb timeout for now
setTimeout(connect, 2000);

function getChromeInstance() {
  return new Promise((res, rej) => {
    Chrome(function (chromeInstance) {
      res(chromeInstance);
    }).on('error', rej);
  });
}

function connect() {
  var request_data = {}
  var response_data = []
  var timeout = 10000;

  //This is where the final data will exist for a website
  function printDataAndExit(){
    console.log(JSON.stringify(request_data, null, 4));
    for(var k in request_data){
                            
    }

    headless.kill();
    process.exit(0); 
  }
 
  setTimeout(printDataAndExit, timeout);
  
  getChromeInstance().then(instance => {
    instance.Network.responseReceived(function(data){
      //This request was sent out
      if(data.response.url in request_data){
        request_data[data.response.url].response = data.response;
      }
    });
    
    instance.Network.requestWillBeSent(function(data){
      if(!(data.request.url in request_data)){
        request_data[data.request.url] = {}
        request_data[data.request.url].numberOfTimesRequested = 0;
      }
      request_data[data.request.url].data = data
      request_data[data.request.url].numberOfTimesRequested += 1;
    });

    instance.Page.enable();
    instance.Network.enable();

    instance.Network.setUserAgentOverride({userAgent: 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_10_5) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/52.0.2743.116 Safari/537.36'});
        
    instance.once('ready', () => {
      instance.Page.navigate({url: screenshotUrl})
    });
  });
}
