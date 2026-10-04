const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const ui = {URL, URLSearchParams};
vm.createContext(ui);
vm.runInContext(fs.readFileSync(path.resolve(__dirname, '../web/widgets.js'), 'utf8'), ui);

test('family path preserves the actual provider query and explicit filter', () => {
  const source = 'plugin://plugin.video.pov/?mode=build_movie_list&action=tmdb_movies_popular&name=Kids%20%26%20Family';
  const result = new URL(ui.familyWidgetPath(source, '12A'));
  assert.equal(result.hostname, 'service.kodi.addonadmin');
  assert.equal(result.searchParams.get('source'), source);
  assert.equal(result.searchParams.get('family_only'), 'true');
  assert.equal(result.searchParams.get('max_rating'), '12A');
});

test('export/import carries original sources across desktop and Shield origins', () => {
  const draft = {label:'Kids',maxRating:'PG',rows:[{label:'Popular',path:'plugin://plugin.video.pov/?mode=build_movie_list&action=tmdb_movies_popular',breadcrumb:['POV','Movies','Popular'],filtered:true}]};
  const plan = ui.widgetPlan(draft);
  assert.match(plan.rows[0].path, /plugin:\/\/service\.kodi\.addonadmin/);
  const restored = ui.parseWidgetPlan(JSON.parse(JSON.stringify(plan)));
  assert.deepEqual(JSON.parse(JSON.stringify(restored)), draft);
  assert.equal(draft.rows[0].path.startsWith('plugin://plugin.video.pov/'), true);
});

test('import rejects missing sources, unrelated URLs and unknown ratings', () => {
  const plan = {label:'Kids', max_rating:'12A',rows:[{label:'Movies',source_path:'plugin://plugin.video.pov/'}]};
  for (const source of ['', 'https://example.com', 'plugin://service.kodi.addonadmin/?mode=family', 'plugin://plugin.video.pov/\n']) {
    assert.throws(() => ui.parseWidgetPlan({...plan,rows:[{label:'Movies',source_path:source}]}));
  }
  assert.throws(() => ui.parseWidgetPlan({...plan,max_rating:'18'}));
});

test('artwork accepts supported HTTPS artwork, not arbitrary file or remote paths', () => {
  assert.equal(ui.widgetPoster({thumbnail:'image://https%3A%2F%2Fimage.tmdb.org%2Ft%2Fp%2Fw500%2Fposter.jpg/'}), 'https://image.tmdb.org/t/p/w500/poster.jpg');
  for (const thumbnail of ['file:///private/image.jpg','http://image.tmdb.org/image.jpg','https://arbitrary.example/image.jpg','image://%broken']) assert.equal(ui.widgetPoster({thumbnail}), '');
});

test('unfiltered source output preserves provider routes and never inherits a global family filter', () => {
  const source = 'plugin://plugin.video.pov/?mode=build_movie_list&action=tmdb_movies_popular&name=All%20Movies';
  assert.equal(ui.widgetOutputPath({path:source,filtered:false,maxRating:'PG'}),source);
  const plan = ui.widgetPlan({label:'Movies',maxRating:'PG',rows:[{label:'Popular',path:source,filtered:false}]});
  assert.equal(plan.family_only,false);
  assert.equal(plan.rows[0].path,source);
  assert.equal(plan.rows[0].source_path,source);
});

test('generic layout body preserves row identity, native action and dynamic source exactly', () => {
  const dynamic = '$VAR[widgetSourcePath]';
  const action = 'ActivateWindow(Videos,$VAR[widgetSourcePath],return)';
  const native = ui.widgetSource({id:'row-native-7',label:'Continue watching',path:dynamic,action});
  const body = JSON.parse(JSON.stringify(ui.widgetLayoutBody({section_id:'existing:home',label:'Home',rows:[native]})));
  assert.deepEqual(body,{section_id:'existing:home',label:'Home',rows:[{id:'row-native-7',label:'Continue watching',path:dynamic,action}]});
  assert.equal(native.path,dynamic);
  const newBody = ui.widgetLayoutBody({section_id:'new',label:'New',rows:[{label:'Popular',path:'plugin://plugin.video.pov/?mode=build_movie_list',filtered:false}]});
  assert.equal(Object.hasOwn(newBody,'section_id'),false);
  assert.equal(Object.hasOwn(newBody.rows[0],'id'),false);
});

test('catalogue media previews respect navigation and blocked classifications even with inherited artwork metadata', () => {
  const movie = {classification:'media',label:'Movie',year:2024,genre:['Drama']};
  const next = {classification:'navigation',label:'Next page',year:2024,mpaa:'PG',genre:['Family'],type:'movie'};
  const blocked = {classification:'blocked',label:'Setup',year:2024,genre:['Family']};
  assert.deepEqual(JSON.parse(JSON.stringify(ui.widgetMediaItems({items:[movie,next,blocked]}))),[movie]);
  assert.equal(ui.widgetMediaItems({items:[{label:'Older service movie',type:'movie'}]}).length,1);
});

test('tabs follow enabled menu entry order and do not promote widget rows to sections', () => {
  const recentlyWatched = {id:'recent',label:'Recently Watched',path:'plugin://plugin.video.pov/?mode=history'};
  const layout = {sections:[
    {id:'hub:movies',label:'Movies hub',rows:[recentlyWatched]},
    {id:'hub:shows',label:'Shows hub',rows:[]},
    {id:'hub:customhub',label:'Custom hub',rows:[]},
    {id:'hub:newpopular',label:'New & Popular',rows:[]},
    {id:'other',label:'Recently Watched',rows:[]}
  ],menu_entries:[
    {id:'favorites-menu',label:'Favorites',target_section_id:'hub:customhub',kind:'hub',disabled:false},
    {id:'newpopular-menu',label:'New & Popular',target_section_id:'hub:newpopular',disabled:true},
    {id:'shows-menu',label:'Shows',target_section_id:'hub:shows',kind:'hub',disabled:false},
    {id:'movies-menu',label:'Movies',target_section_id:'hub:movies',kind:'hub',disabled:false}
  ]};
  const visible = JSON.parse(JSON.stringify(ui.widgetVisibleSections(layout)));
  assert.deepEqual(visible.map(section=>section.label),['Favorites','Shows','Movies']);
  assert.deepEqual(visible.map(section=>section.menu_id),['favorites-menu','shows-menu','movies-menu']);
  assert.equal(visible.some(section=>section.label==='Recently Watched'),false);
  assert.equal(visible[2].rows[0].label,'Recently Watched');
  assert.equal(layout.sections[0].label,'Movies hub');
});

test('older section metadata keeps real menu order and excludes disabled or absent sections', () => {
  const sections = [
    {id:'movies',label:'Movies',action:'movies'},
    {id:'hidden',label:'New & Popular',action:'new',disabled:true},
    {id:'outside',label:'Outside menu',in_menu:false},
    {id:'shows',label:'Shows',action:'shows'},
    {id:'mainmenu',rows:[{label:'Shows',action:'shows'},{label:'Movies',action:'movies'}]}
  ];
  assert.deepEqual(JSON.parse(JSON.stringify(ui.widgetVisibleSections({sections}))).map(section=>section.label),['Shows','Movies']);
  assert.equal(ui.widgetVisibleSections({sections,menu_entries:[]}).length,0);
});

test('native source descriptions identify playlists addons favourites and skin variables', () => {
  for (const [row,label] of [
    [{path:'special://videoplaylists/'},'Kodi · Video playlists'],
    [{path:'addons://sources/video/'},'Kodi · Installed video add-ons'],
    [{action:'ActivateWindow(FavouritesBrowser)'},'Kodi · Favourites'],
    [{path:'$VAR[widgetSourcePath]'},'Bingie · Skin-defined source']
  ]) assert.equal(ui.widgetSourceDescription(row),label);
  assert.equal(ui.widgetSourceDescription({path:'plugin://plugin.video.pov/?mode=build_movie_list'}),'');
});

function catalogueHarness(layoutRows=[], options={}) {
  const elements = new Map(), handlers = {}, storage = options.storage || new Map(), calls = [];
  const node = () => {
    let html='';
    return {value:'',checked:false,hidden:false,disabled:false,isConnected:true,textContent:'',dataset:{},children:[],
      get innerHTML(){return html;},set innerHTML(value){html=value;for(const child of this.children){child.isConnected=false;elements.delete('#'+child.id);}this.children=[];},
      append(element){this.children.push(element);element.isConnected=true;elements.set('#'+element.id,element);},
      scrollIntoView(){},showModal(){},close(){},click(){}};
  };
  const get = selector => {
    if (/^#bs-folder-\d+$/.test(selector)) return elements.get(selector) || null;
    if (!elements.has(selector)) elements.set(selector,node());
    return elements.get(selector);
  };
  const pageLabels=[node(),node()],pageButtons=[-1,1,-1,1].map(step=>({...node(),dataset:{pageStep:String(step)}}));
  const root = {...node(),querySelector:get,querySelectorAll:selector=>selector==='.bs-page-label' ? pageLabels : selector==='[data-page-step]' ? pageButtons : [],addEventListener:(name,handler)=>{handlers[name]=handler;}};
  const rootPath='plugin://plugin.video.pov/', menuPath='plugin://plugin.video.pov/?mode=navigator_movies';
  const mediaPath='plugin://plugin.video.pov/?mode=build_movie_list&action=popular';
  const seriesPath='plugin://plugin.video.pov/?mode=build_season_list&tvshow_id=11';
  const blockedPath='not-a-plugin-route';
  const folder=(label,path,extra={})=>({label,path,filetype:'directory',classification:'menu',traversable:true,...extra});
  const bad=folder('Malformed source',blockedPath,{classification:'blocked',traversable:false,browseable:false,skip_reason:'Invalid folder path.'});
  const replies = new Map([
    [rootPath,{classification:'menu',can_use_as_widget:false,items:[folder('Movies',menuPath),bad],children:[folder('Movies',menuPath)],skips:[{...bad,reason:bad.skip_reason}]}],
    [menuPath,{classification:'menu',can_use_as_widget:false,items:[folder('Popular',mediaPath)],children:[folder('Popular',mediaPath)],skips:[]}],
    [mediaPath,{classification:'media_list',can_use_as_widget:true,items:[{label:'A show',path:seriesPath,filetype:'directory',classification:'media',type:'tvshow',year:2025}],children:[],skips:[{label:'A show',path:seriesPath,reason:'Individual shows are not auto-expanded.',classification:'media'}],sample:{truncated:true,message:'Truncated preview'}}],
  ]);
  const lists=[];
  if(options.listCount){
    for(let i=0;i<options.listCount;i++){
      const item=folder('List '+String(i+1).padStart(2,'0'),mediaPath+'&list='+i,{usefulness:{score:200-i,reason:'Observed list preference',inferred:true}});
      lists.push(item);
      replies.set(item.path,{classification:'media_list',can_use_as_widget:true,items:[{label:'Title '+i,type:'movie',classification:'media'}],children:[],skips:[]});
    }
    replies.set(rootPath,{classification:'menu',items:[folder('Movies',menuPath)],children:[folder('Movies',menuPath)]});
    replies.set(menuPath,{classification:'menu',items:[...lists].reverse(),children:[...lists].reverse()});
  }
  if(options.configure)options.configure({replies,lists,folder,rootPath,menuPath,mediaPath});
  const context = {URL,URLSearchParams,AbortController,console,setTimeout,clearTimeout,esc:value=>String(value ?? '').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c])),out:()=>{},
    document:{querySelector:()=>root,createElement:()=>node()},window:{addEventListener(){}},localStorage:{getItem:key=>storage.get(key),setItem:(key,value)=>storage.set(key,value),removeItem:key=>storage.delete(key)},
    IntersectionObserver:class {constructor(callback){context.intersection=callback;}observe(){}disconnect(){}},navigator:{clipboard:{writeText:async()=>{}}},prompt:()=>null,confirm:()=>true,
    api:async (path,body)=>{
      calls.push({path,body});
      if(path==='/api/widgets/sources')return {sources:options.sources || [{addon_id:'plugin.video.pov',label:'POV',path:rootPath,enabled:true,traversable:true}]};
      if(path==='/api/widgets/layout')return {revision:'revision-1',max_rows:20,sections:[{id:'section-1',label:options.sectionLabel || 'Movies',kind:options.sectionKind || 'hub',editable:options.editable !== false,rows:layoutRows}],new_section:{available:false}};
      if(path==='/api/widgets/row-preview' && options.rowPreview)return options.rowPreview;
      if(path==='/api/widgets/browse' && replies.has(body.path)){
        if(options.browse) return options.browse(body.path,replies.get(body.path));
        return replies.get(body.path);
      }
      throw new Error('Unexpected request '+path+' '+body?.path);
    }};
  vm.createContext(context);
  vm.runInContext(fs.readFileSync(path.resolve(__dirname,'../web/widgets.js'),'utf8'),context);
  return {context,elements,handlers,storage,calls,rootPath,menuPath,mediaPath,seriesPath,blockedPath,replies,lists,pageLabels,pageButtons,
    rows:()=>get('#bs-folders').children,
    click:dataset=>handlers.click({target:{closest:()=>({dataset})}})};
}

async function drainCatalogue(){for(let n=0;n<5;n++)await new Promise(resolve=>setImmediate(resolve));}
async function settleCatalogue(harness) {
  await harness.context.widgetStudioView();
  await drainCatalogue();
}

test('saved native row previews use IDs while preserving original source and action', async () => {
  const original = {id:'playlist-row',label:'Video playlists',path:'special://videoplaylists/',action:'ActivateWindow(Videos,special://videoplaylists/,return)'};
  const before = JSON.stringify(original);
  const h=catalogueHarness([original],{editable:false,rowPreview:{status:'ok',items:[{label:'Family movies playlist',filetype:'directory'}]}});
  await settleCatalogue(h);
  const previews=h.calls.filter(call=>call.path==='/api/widgets/row-preview');
  assert.equal(previews.length,1);
  assert.deepEqual(JSON.parse(JSON.stringify(previews[0].body)),{section_id:'section-1',row_id:'playlist-row',limit:48});
  assert.equal(Object.hasOwn(previews[0].body,'path'),false);
  assert.equal(Object.hasOwn(previews[0].body,'action'),false);
  assert.equal(JSON.stringify(original),before);
  assert.ok(!h.calls.some(call=>call.path==='/api/widgets/browse' && call.body.path===original.path));
  assert.ok(!h.calls.some(call=>/layout\/(apply|rebuild)/.test(call.path)));
  assert.match(h.elements.get('#bs-current-rows').innerHTML,/Kodi · Video playlists/);
  assert.match(h.elements.get('#bs-current-rows').innerHTML,/value="special:\/\/videoplaylists\/"/);
  assert.match(h.elements.get('[data-preview-row="0"]').innerHTML,/Family movies playlist/);
  assert.equal(h.elements.get('#bs-review').disabled,true);
});

test('unchanged saved family rows use full row-preview while changed ratings and filters use draft previews', async () => {
  const source='plugin://plugin.video.pov/?mode=build_tvshow_list&action=in_progress_tvshows';
  const wrapper=ui.familyWidgetPath(source,'12A');
  const original={id:'saved-family',label:'Continuing kids shows',path:wrapper,action:`ActivateWindow(Videos,${wrapper},return)`};
  const before=JSON.stringify(original);
  const h=catalogueHarness([original],{sources:[],rowPreview:{status:'ok',items:[{label:'Later-page saved title',type:'tvshow',classification:'media'}]},configure:({replies})=>replies.set(source,{items:[{label:'Unfiltered draft title',type:'tvshow',classification:'media'}],family_preview:{files:[{label:'PG draft title',type:'tvshow',classification:'media'}]},children:[]})});
  await settleCatalogue(h);
  assert.equal(h.calls.filter(call=>call.path==='/api/widgets/row-preview').length,1);
  assert.ok(!h.calls.some(call=>call.path==='/api/widgets/browse' && call.body.path===source));
  assert.match(h.elements.get('[data-preview-row="0"]').innerHTML,/Later-page saved title/);
  const change=async value=>{const select={value,dataset:{rowFilter:'0'}};h.handlers.change({target:{closest:selector=>selector==='[data-row-filter]' ? select : null}});await drainCatalogue();};
  await change('PG');
  const drafts=h.calls.filter(call=>call.path==='/api/widgets/browse' && call.body.path===source);
  assert.equal(drafts.filter(call=>call.body.family_preview===true).length,1);
  assert.equal(drafts.at(-1).body.max_rating,'PG');
  assert.match(h.elements.get('[data-preview-row="0"]').innerHTML,/PG draft title/);
  const beforeUnfiltered=h.calls.length;
  await change('none');
  assert.ok(!h.calls.slice(beforeUnfiltered).some(call=>call.body?.family_preview===true));
  assert.match(h.elements.get('[data-preview-row="0"]').innerHTML,/Unfiltered draft title/);
  await change('12A');
  assert.equal(h.calls.filter(call=>call.path==='/api/widgets/row-preview').length,1,'Restoring the saved filter reuses its ID preview');
  assert.match(h.elements.get('[data-preview-row="0"]').innerHTML,/Later-page saved title/);
  assert.equal(JSON.stringify(original),before);
  assert.ok(!h.calls.some(call=>/layout\/(apply|rebuild)/.test(call.path)));
});

test('verified Home widgets accept row reorder drafts without changing native actions or applying', async () => {
  const rows = [{id:'home:first',label:'First',path:'$VAR[HomeContent]',action:'ActivateWindow(Videos,$VAR[HomeContent],return)'},{id:'home:second',label:'Second',path:'special://videoplaylists/',action:'ActivateWindow(Videos,special://videoplaylists/,return)'}];
  const h=catalogueHarness(rows,{sectionLabel:'Home',sectionKind:'home',rowPreview:{status:'ok',items:[]}});
  await settleCatalogue(h);
  assert.equal(h.elements.get('#bs-add-row').disabled,false);
  assert.match(h.elements.get('#bs-section-detail').textContent,/Home screen/);
  await h.click({moveRow:'0,1'});
  const draft=JSON.parse(h.storage.get('bingie_studio_drafts_v2'))['section-1'];
  assert.deepEqual(draft.rows.map(row=>row.id),['home:second','home:first']);
  assert.equal(draft.rows[1].action,rows[0].action);
  assert.equal(draft.rows[1].path,rows[0].path);
  assert.equal(h.elements.get('#bs-review').disabled,false);
  assert.ok(!h.calls.some(call=>/layout\/(apply|rebuild)/.test(call.path)));
});

test('catalogue uses observed paths to preview a media row without traversing individual shows', async () => {
  const h=catalogueHarness();
  await settleCatalogue(h);
  const browse=h.calls.filter(call=>call.path==='/api/widgets/browse');
  assert.deepEqual(browse.map(call=>call.body.path),[h.rootPath,h.menuPath,h.mediaPath]);
  assert.ok(browse.every(call=>call.body.family_preview===false));
  assert.ok(!browse.some(call=>call.body.path===h.seriesPath || call.body.path===h.blockedPath));
  const contents=[...h.elements.entries()].filter(([key])=>/^#bs-folder-\d+$/.test(key)).map(([,node])=>node.innerHTML).join('');
  assert.match(contents,/A show/);
  assert.match(contents,/Truncated preview/);
});

test('blocked menu children remain a visible folder placeholder without issuing a browse request', async () => {
  const h=catalogueHarness();
  await settleCatalogue(h);
  const rows=[...h.elements.entries()].filter(([key])=>/^#bs-folder-\d+$/.test(key)).map(([,node])=>node.innerHTML);
  assert.ok(rows.some(markup=>markup.includes('<h4>Malformed source') && markup.includes('Invalid folder path.')));
  assert.ok(!h.calls.some(call=>call.path==='/api/widgets/browse' && call.body.path===h.blockedPath));
});

test('adding a discovered catalogue row creates an unfiltered draft without changing TV state', async () => {
  const h=catalogueHarness();
  await settleCatalogue(h);
  const [entryKey]=[...h.elements.entries()].find(([key,node])=>/^#bs-folder-\d+$/.test(key) && node.innerHTML.includes('<h4>Popular'));
  const id=entryKey.match(/\d+/)[0];
  await h.handlers.click({target:{closest:()=>({dataset:{addSource:id}})}});
  const drafts=JSON.parse(h.storage.get('bingie_studio_drafts_v2'));
  assert.equal(drafts['section-1'].rows[0].path,h.mediaPath);
  assert.equal(drafts['section-1'].rows[0].filtered,false);
  assert.ok(!h.calls.some(call=>call.path==='/api/widgets/layout/apply'));
});

test('replacing an existing source keeps its row identity and original action for backend validation', async () => {
  const original={id:'existing-8',label:'Existing row',path:'$VAR[widgetSourcePath]',action:'ActivateWindow(Videos,$VAR[widgetSourcePath],return)',filtered:false};
  const h=catalogueHarness([original]);
  await settleCatalogue(h);
  await h.handlers.click({target:{closest:()=>({dataset:{replaceRow:'0'}})}});
  const [entryKey]=[...h.elements.entries()].find(([key,node])=>/^#bs-folder-\d+$/.test(key) && node.innerHTML.includes('<h4>Popular'));
  await h.handlers.click({target:{closest:()=>({dataset:{addSource:entryKey.match(/\d+/)[0]}})}});
  const drafts=JSON.parse(h.storage.get('bingie_studio_drafts_v2'));
  const row=drafts['section-1'].rows[0];
  assert.equal(row.id,original.id);
  assert.equal(row.label,original.label);
  assert.equal(row.action,original.action);
  assert.equal(row.path,h.mediaPath);
  assert.equal(row.filtered,false);
  assert.equal(drafts['section-1'].rows.length,1);
  assert.ok(!h.calls.some(call=>call.path==='/api/widgets/layout/apply'));
});

function visibleLabels(h){return h.rows().map(row=>row.innerHTML.match(/<h4>([^<]+)/)?.[1]);}
function mediaRequests(h){const paths=new Set(h.lists.map(item=>item.path));return h.calls.filter(call=>call.path==='/api/widgets/browse'&&paths.has(call.body.path)).map(call=>call.body.path);}

test('catalogue ranks observed usefulness and previews only the current twelve-folder page', async () => {
  const h=catalogueHarness([], {listCount:26});
  await settleCatalogue(h);
  assert.equal(h.rows().length,12);
  assert.deepEqual(visibleLabels(h),h.lists.slice(0,12).map(item=>item.label));
  assert.deepEqual(mediaRequests(h),h.lists.slice(0,12).map(item=>item.path));
  assert.equal(h.calls.filter(call=>call.path==='/api/widgets/browse').length,14,'Only root, Movies menu and page-one lists should be read');
  assert.match(h.pageLabels[0].textContent,/Page 1 of 3.*1–12 of 27/);
  assert.equal(h.pageButtons[0].disabled,true);
  assert.equal(h.pageButtons[1].disabled,false);
  assert.ok(h.calls.filter(call=>call.path==='/api/widgets/browse').every(call=>call.body.family_preview===false));
});

test('Next previews the next twelve rows and Previous reuses cached previews', async () => {
  const h=catalogueHarness([], {listCount:26});
  await settleCatalogue(h);
  await h.click({pageStep:'1'});await drainCatalogue();
  assert.deepEqual(visibleLabels(h),h.lists.slice(12,24).map(item=>item.label));
  assert.deepEqual(mediaRequests(h),h.lists.slice(0,24).map(item=>item.path));
  assert.match(h.pageLabels[1].textContent,/Page 2 of 3.*13–24 of 27/);
  assert.equal(h.pageButtons[0].disabled,false);
  await h.click({pageStep:'-1'});await drainCatalogue();
  assert.deepEqual(visibleLabels(h),h.lists.slice(0,12).map(item=>item.label));
  assert.equal(mediaRequests(h).length,24);
  await h.click({pageStep:'1'});await drainCatalogue();
  await h.click({pageStep:'1'});await drainCatalogue();
  assert.deepEqual(visibleLabels(h),[...h.lists.slice(24).map(item=>item.label),'Movies']);
  assert.equal(h.rows().length,3);
  assert.equal(h.pageButtons[1].disabled,true);
  assert.equal(mediaRequests(h).length,26);
});

test('a delayed previous-page response cannot overwrite the current page or continue its request queue', async () => {
  let resolveOld;
  const delayed=new Promise(resolve=>{resolveOld=resolve;});
  const h=catalogueHarness([], {listCount:26,browse:(source,result)=>source.endsWith('&list=0') ? delayed : result});
  await settleCatalogue(h);
  assert.deepEqual(mediaRequests(h),[h.lists[0].path]);
  await h.click({pageStep:'1'});await drainCatalogue();
  // The bounded post-batch sort promotes the checked page to the front. This
  // page now displays untested replacements, which must not auto-fetch.
  const afterPage = visibleLabels(h);
  assert.deepEqual(afterPage,h.lists.slice(0,12).map(item=>item.label));
  resolveOld({...h.replies.get(h.lists[0].path),items:[{label:'OLD PAGE TITLE',type:'movie',classification:'media'}]});
  await drainCatalogue();
  assert.deepEqual(visibleLabels(h),afterPage);
  assert.ok(h.rows().every(row=>!row.innerHTML.includes('OLD PAGE TITLE')));
  assert.deepEqual(mediaRequests(h),[h.lists[0].path,...h.lists.slice(12,24).map(item=>item.path)]);
  assert.match(h.pageLabels[0].textContent,/Page 2 of 3/);
});

test('discovered children remain available after one bounded rebucket without recursively fetching replacements', async () => {
  let discovered;
  const h=catalogueHarness([], {listCount:26,configure:({replies,lists,folder})=>{
    discovered=folder('Discovered favourite',lists[0].path+'&child=1',{usefulness:{score:999,reason:'New observed folder',inferred:true}});
    replies.set(lists[0].path,{classification:'menu',items:[discovered],children:[discovered]});
    replies.set(discovered.path,{classification:'media_list',can_use_as_widget:true,items:[{label:'New discovery title',type:'movie',classification:'media'}],children:[]});
  }});
  await settleCatalogue(h);
  assert.deepEqual(visibleLabels(h),h.lists.slice(1,13).map(item=>item.label));
  assert.equal(mediaRequests(h).length,12);
  assert.ok(h.rows().at(-1).innerHTML.includes('Load preview'));
  assert.equal(h.calls.filter(call=>call.body?.path===discovered.path).length,0);
  h.elements.get('#bs-search').value='Discovered favourite';
  h.elements.get('#bs-sort').onchange();
  await drainCatalogue();
  assert.deepEqual(visibleLabels(h),[discovered.label]);
  assert.equal(h.calls.filter(call=>call.path==='/api/widgets/browse'&&call.body.path===discovered.path).length,1);
  assert.ok(h.rows().some(row=>row.innerHTML.includes('New discovery title')));
});

test('source checkboxes default to enabled POV and TMDb helpers, keep Fen off, and persist All and None', async () => {
  const sources=['plugin.video.pov','plugin.video.tmdb.bingie.helper','plugin.video.fenlight','plugin.video.iplayerwww'].map(addon_id=>({addon_id,label:addon_id,path:'plugin://'+addon_id+'/',enabled:true,traversable:true}));
  const configure=({replies})=>sources.slice(1).forEach(source=>replies.set(source.path,{items:[],children:[],classification:'empty'}));
  const h=catalogueHarness([], {sources,configure});
  await settleCatalogue(h);
  const markup=h.elements.get('#bs-source-options').innerHTML;
  assert.match(markup,/data-catalogue-source="plugin.video.pov" checked/);
  assert.match(markup,/data-catalogue-source="plugin.video.tmdb.bingie.helper" checked/);
  assert.doesNotMatch(markup,/data-catalogue-source="plugin.video.fenlight" checked/);
  assert.ok(h.calls.some(call=>call.body?.path===sources[1].path));
  assert.ok(!h.calls.some(call=>call.body?.path===sources[2].path));
  await h.click({sourceChoice:'all'});await drainCatalogue();
  assert.deepEqual(JSON.parse(h.storage.get('bingie_studio_sources_v1')),sources.map(source=>source.addon_id));
  assert.ok(h.calls.some(call=>call.body?.path===sources[2].path));
  await h.click({sourceChoice:'none'});await drainCatalogue();
  assert.deepEqual(JSON.parse(h.storage.get('bingie_studio_sources_v1')),[]);
  assert.equal(h.rows().length,0);
  const reloaded=catalogueHarness([], {sources,configure,storage:h.storage});
  await settleCatalogue(reloaded);
  assert.equal(reloaded.calls.filter(call=>call.path==='/api/widgets/browse').length,0);
  assert.equal(reloaded.elements.get('#bs-source-summary').textContent,'0 of 4 sources selected');
});

test('individual source changes preserve multiple selections and persist an explicit Fen preference', async () => {
  const fen={addon_id:'plugin.video.fenlight',label:'Fen Light',path:'plugin://plugin.video.fenlight/',enabled:true};
  const h=catalogueHarness([], {sources:[{addon_id:'plugin.video.pov',label:'POV',path:'plugin://plugin.video.pov/',enabled:true},fen],configure:({replies})=>replies.set(fen.path,{items:[],children:[]})});
  await settleCatalogue(h);
  const change=async checked=>{const input={checked,dataset:{catalogueSource:fen.addon_id}};h.handlers.change({target:{closest:selector=>selector==='[data-catalogue-source]' ? input : null}});await drainCatalogue();};
  await change(true);
  assert.deepEqual(JSON.parse(h.storage.get('bingie_studio_sources_v1')),['plugin.video.pov',fen.addon_id]);
  await change(false);
  assert.deepEqual(JSON.parse(h.storage.get('bingie_studio_sources_v1')),['plugin.video.pov']);
  assert.ok(h.rows().length);
});

test('confirmed empty and failed popular folders move last once without replacement preview storms', async () => {
  const h=catalogueHarness([], {listCount:26,configure:({replies,lists})=>replies.set(lists[0].path,{classification:'empty',items:[],children:[]}),browse:(path,result)=>{if(path.endsWith('&list=1'))throw Error('Provider unavailable');return result;}});
  await settleCatalogue(h);
  assert.deepEqual(visibleLabels(h),h.lists.slice(2,14).map(item=>item.label));
  assert.equal(mediaRequests(h).length,12,'The two promoted unknown replacements must not load automatically');
  assert.ok(h.rows().slice(-2).every(row=>row.innerHTML.includes('Load preview')));
  const records=JSON.parse(h.storage.get('bingie_studio_catalogue_checks_v1')).entries;
  assert.equal(records.find(([path])=>path===h.lists[0].path)[1].kind,'empty');
  assert.equal(records.find(([path])=>path===h.lists[1].path)[1].kind,'error');
  assert.ok(records.every(([,record])=>!Object.hasOwn(record,'items')));
  const reload=catalogueHarness([], {listCount:26,storage:h.storage});
  await settleCatalogue(reload);
  assert.equal(mediaRequests(reload).length,12);
  assert.ok(!mediaRequests(reload).includes(reload.lists[0].path));
  assert.ok(!mediaRequests(reload).includes(reload.lists[1].path));
  await reload.click({pageStep:'1'});await drainCatalogue();
  await reload.click({pageStep:'1'});await drainCatalogue();
  const recovered=JSON.parse(reload.storage.get('bingie_studio_catalogue_checks_v1')).entries;
  assert.equal(recovered.find(([path])=>path===reload.lists[0].path)[1].kind,'media');
  assert.equal(recovered.find(([path])=>path===reload.lists[1].path)[1].kind,'media');
  assert.ok(reload.rows().some(row=>row.innerHTML.includes('Title 0')));
  assert.ok(reload.rows().some(row=>row.innerHTML.includes('Title 1')));
});

test('unknown folders are distinct from cached empty folders and stale cache entries expire', () => {
  const now=30000000;
  const raw=JSON.stringify({entries:[
    ['plugin://plugin.video.pov/?empty=1',{kind:'empty',count:0,checkedAt:now-1000}],
    ['plugin://plugin.video.pov/?old=1',{kind:'empty',count:0,checkedAt:now-21600001}],
    ['plugin://plugin.video.pov/?error=1',{kind:'error',count:0,checkedAt:now-900001}],
  ]});
  const cache=ui.widgetCatalogueCache(raw,now);
  assert.equal(cache.size,1);
  assert.equal(ui.widgetCatalogueObservation(null,'queued').kind,'unknown');
  assert.ok(ui.widgetCatalogueTier({kind:'unknown'})>ui.widgetCatalogueTier(cache.values().next().value));
  assert.equal(ui.widgetCatalogueCache('invalid',now).size,0);
});

test('Load preview reads only the explicitly promoted folder and does not start another page batch', async () => {
  const h=catalogueHarness([], {listCount:26,configure:({replies,lists})=>replies.set(lists[0].path,{classification:'empty',items:[],children:[]})});
  await settleCatalogue(h);
  const unknown=h.rows().at(-1);
  assert.match(unknown.innerHTML,/<h4>List 13/);
  const id=unknown.innerHTML.match(/data-load-folder="(\d+)"/)[1];
  await h.click({loadFolder:id});await drainCatalogue();
  assert.equal(mediaRequests(h).length,13);
  assert.equal(mediaRequests(h).at(-1),h.lists[12].path);
  assert.ok(h.rows().some(row=>row.innerHTML.includes('Title 12')));
  assert.ok(!mediaRequests(h).includes(h.lists[13].path));
});
