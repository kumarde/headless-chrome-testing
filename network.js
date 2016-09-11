var Chrome = require('chrome-remote-interface');
var spawn = require('child_process').spawn;
var tree = require('./tree.js');
var fs = require('fs');
var Queue = require('./queue.js');

var Node = require('tree-node');

const url = require('url')

if (process.argv[2] === undefined) {
    throw Error('No headless binary path provided.');
}

var headless = spawn(process.argv[2], [
        '--remote-debugging-port=9222']);

var screenshotUrl = process.argv[3] || 'https://paulirish.com';
var input_hostname = url.parse(screenshotUrl).hostname;

var outputFile = process.argv[4] || "outfile";


// Dumb timeout for now
setTimeout(connect, 2000);

function getChromeInstance() {
    return new Promise((res, rej) => {
            Chrome(function (chromeInstance) {
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
    var timeout = 10000;
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
                        child_data = undefined
                        if(request_data[child_url] !== undefined){
                            child_data = request_data[child_url]; 
                        }

                        outputTree.add(child_url, parent_url, child_data, outputTree.traverseBF); 
                    }
                }

                for(var i = 0; i < current.resources.length; ++i){
                    resource_url = cleanURL(current.resources[i].url);
                    if(request_data[resource_url] !== undefined){
                        if(parent_url == resource_url){
                            continue;    
                        }
                        outputTree.add(resource_url, parent_url, request_data[resource_url], outputTree.traverseBF);
                    }
                }
            }
            
            fs.writeFileSync(outputFile, JSON.stringify(outputTree, null, 4));

            headless.kill();
            process.exit(0);
        });    
    }

    getChromeInstance().then(instance => {
            instance.Network.responseReceived(function(data){
                data.response.url = cleanURL(data.response.url);

                //This request was sent out for the appropriate response
                if(data.response.url in request_data){
                request_data[data.response.url].response = data.response;
                }
                });

            instance.Network.requestWillBeSent(function(data){
                //find the appropriate "root"
                data.request.url = cleanURL(data.request.url);

                if(data.redirectResponse != null && numConnections < 3){
                delete request_data[root_domain];  
                root_domain = data.request.url;
                }

                if(!(data.request.url in request_data)){
                request_data[data.request.url] = {}
                request_data[data.request.url].numberOfTimesRequested = 0;
                }

                request_data[data.request.url].data = data
                request_data[data.request.url].numberOfTimesRequested += 1;

                ++numConnections;
                });

            instance.Page.loadEventFired(getResourceTree.bind(null, instance));

            instance.Page.enable();
            instance.Network.enable();

            instance.Network.setUserAgentOverride({userAgent: 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_10_5) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/52.0.2743.116 Safari/537.36'});

            instance.once('ready', () => {
                    instance.Page.navigate({url: screenshotUrl})
                    });
    });
}
