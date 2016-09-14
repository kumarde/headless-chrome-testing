var Chrome = require('chrome-remote-interface');
var spawn = require('child_process').spawn;
var tree = require('./tree.js');
var fs = require('fs');
var Queue = require('./queue.js');

const url = require('url')

if (process.argv.length != 6){
    throw Error('incorrect usage');    
}

if (process.argv[2] === undefined) {
    throw Error('No headless binary path provided.');
}

var screenshotUrl = process.argv[3] || 'https://paulirish.com';
var input_hostname = url.parse(screenshotUrl).hostname;

var outputFile = process.argv[4] || "outfile";

var port = process.argv[5];

var headless = spawn(process.argv[2], [
       '--no-sandbox', '--remote-debugging-port='+port]);

headless.stderr.on('data', (data) => {
    var err_string = `${data}`;
    if(err_string.includes('errno=98') != false){
        console.log(err_string);
        headless.kill();
        process.exit(98);    
    } 
});

// Dumb timeout for now
setTimeout(connect, 2000);

function statusInErrorRange(code){
    if(code >= 400 && code < 600){
        return true;    
    }    
    return false;
}

function getChromeInstance() {
    return new Promise((res, rej) => {
        Chrome({port: port}, function (chromeInstance) {
            res(chromeInstance);
            }).on('error', function(err){
                console.log(err);    
        });
    });
}


function cleanURL(url){
    return url.toLowerCase().replace(/\/+$/,"") + "/";    
}

function connect() {
    var request_data = {}
    var response_data = []
    var timeout = 15000;
    var root_domain = screenshotUrl;
    var numConnections = 0;

    function getResourceTree(instance){
        instance.Page.getResourceTree().then((v) => {
            var root_domain = cleanURL(v.frameTree.frame.url);
            var outputTree = new tree(root_domain, request_data[root_domain]); 
             
            var frameTreeQueue = new Queue();
            var count = 0; 
            frameTreeQueue.enqueue(v.frameTree);
            /*
                frameResourceTree:
                    frame : Object
                    childFrames : [frameResourceTree]
                    resources : [Object]
            */
            
            while(!frameTreeQueue.isEmpty()){
                current = frameTreeQueue.dequeue();
                parent_url = cleanURL(current.frame.url);
                
                if (current.hasOwnProperty("childFrames")){
                    for(var i = 0; i < current.childFrames.length; ++i){
                        frameTreeQueue.enqueue(current.childFrames[i]);
                        child_url = cleanURL(current.childFrames[i].frame.url);
                        child_data = {error: "No network data available for this resource"};
                        if(child_url == parent_url){
                            continue;    
                        }
                        if(request_data[child_url] !== undefined){
                            child_data = {};
                            child_data.numberOfTimesRequested = request_data[child_url].numberOfTimesRequested;
                            child_data.request = request_data[child_url].data.request;
                            child_data.response = {};
                            if(request_data[child_url].hasOwnProperty("response")){
                                child_data.response.url = request_data[child_url].response.url;
                                child_data.response.headers = request_data[child_url].response.headers;
                                child_data.status = request_data[child_url].response.status; 
                            }
                        }
                        count++;
                        outputTree.add(child_url, parent_url, child_data, outputTree.traverseBF); 
                    }
                }

                for(var i = 0; i < current.resources.length; ++i){
                    resource_url = cleanURL(current.resources[i].url);
                    protocol = url.parse(resource_url).protocol;
                    if(protocol !== 'http:' && protocol !== 'https:'){
                        continue;    
                    }
                    
                    child_data = {error: "No network data available for this resource"};
                    
                    if(resource_url == parent_url){
                        continue;
                    }

                    if(request_data[resource_url] !== undefined){
                        child_data = {}; 
                        child_data.numberOfTimesRequested = request_data[resource_url].numberOfTimesRequested;
                        child_data.request = request_data[resource_url].data.request;
                        child_data.response = {};
                        if(request_data[resource_url].hasOwnProperty("response")){
                            child_data.response.url = request_data[resource_url].response.url;
                            child_data.response.headers = request_data[resource_url].response.headers;
                            child_data.response.status = request_data[resource_url].response.status;
                        }
                    }
                    count++;
                    outputTree.add(resource_url, parent_url, child_data, outputTree.traverseBF);
                }
            }
        
            //Add total number of resources found 
            outputTree._root.numResources = count;

            fs.writeFileSync(outputFile, JSON.stringify(outputTree, null, 4));

            headless.kill();

            if(input_hostname.indexOf('www.') == 0){
                process.exit(0);     
            }
            
            if(count == 0 && outputTree._root.response == null){
                process.exit(7); 
            }
            if(count == 0 && statusInErrorRange(outputTree._root.response.status)){
                process.exit(7);    
            }

            process.exit(0);
        }); 
    }

    getChromeInstance().then(instance => {
            instance.Network.responseReceived(function(data){
                if(data.hasOwnProperty('response')){
                    data.response.url = cleanURL(data.response.url);

                    //This request was sent out for the appropriate response
                    if(data.response.url in request_data){
                        request_data[data.response.url].response = data.response;
                    }
                }
            });

            instance.Network.requestWillBeSent(function(data){
                //console.log(data);
                
                data.request.url = cleanURL(data.request.url);
                
                if(!(data.request.url in request_data)){
                    request_data[data.request.url] = {}
                    request_data[data.request.url].numberOfTimesRequested = 0;
                }

                request_data[data.request.url].data = data
                request_data[data.request.url].numberOfTimesRequested += 1;
                
                ++numConnections;
            });
           
            setTimeout(getResourceTree.bind(null, instance), timeout);
            //instance.Page.loadEventFired(getResourceTree.bind(null, instance));

            instance.Page.enable();
            instance.Network.enable();

            mac_firefox_user_agent = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.10; rv:45.0) Gecko/20100101 Firefox/45.0";

            linux_chrome_user_agent = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/53.0.2785.101 Safari/537.36"

            mac_chrome_user_agent = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_10_5) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/52.0.2743.116 Safari/537.36"

            instance.Network.setUserAgentOverride({userAgent: mac_chrome_user_agent});

            instance.once('ready', () => {
                instance.Page.navigate({url: screenshotUrl})
            });
    });
}
