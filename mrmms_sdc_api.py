import glob, os, requests
import pdb # https://pythonconquerstheuniverse.wordpress.com/2009/09/10/debugging-in-python/
from tqdm import tqdm
import datetime as dt
from pymms import mms_utils

class MrMMS_SDC_API:
    """Interface with NASA's MMS SDC API
    
    Interface with the Science Data Center (SDC) API of the
    Magnetospheric Multiscale (MMS) mission.
    https://lasp.colorado.edu/mms/sdc/public/
    
    Params:
        sc (str,list):       Spacecraft IDs ('mms1', 'mms2', 'mms3', 'mms4')
        instr (str,list):    Instrument IDs
        mode (str,list):     Data rate mode ('slow', 'fast', 'srvy', 'brst')
        level (str,list):    Data quality level ('l1a', 'l1b', 'sitl', 'l2pre', 'l2', 'l3')
        anc_product (str):   Name of an ancillary data product. Automatically sets
                             `data_type='ancillary'`.
        data_type (str):     Type of data ('ancillary', 'hk', 'science')
        data_root (str):     Location where MMS directory structure begins
        end_date (str):      End date of data interval, formatted as either %Y-%m-%d or
                             %Y-%m-%dT%H:%M:%S.
        files (str,list):    File names. If set, automatically sets `sc`, `instr`, `mode`,
                             `level`, `optdesc` and `version` to None.
        offline (bool):      Do not search for file information online.
        optdesc (str,list):  Optional file name descriptor
        site (str):          SDC site to use ('public', 'private'). Setting `level`
                             automatically sets `site`. If `level` is 'l2' or 'l3', then
                             `site`='public' otherwise `site`='private'.
        start_date (str):    Start date of data interval, formatted as either %Y-%m-%d or
                             %Y-%m-%dT%H:%M:%S.
        version (str,list):  File version numbers.
    """
    
    def __init__(self, sc=None, instr=None, mode=None, level=None,
                 anc_product=None,
                 data_type='science',
                 data_root=None,
                 end_date=None,
                 files=None,
                 offline=False,
                 optdesc=None,
                 site='public',
                 start_date=None,
                 version=None):
        
        # Set attributes
        #   - Put site before level because level will auto-set site
        #   - Put files last because it will reset most fields
        self.site = site
        
        self.anc_product = anc_product
        self.data_type = data_type
        self.end_date = end_date
        self.instr = instr
        self.level = level
        self.mode = mode
        self.offline = offline
        self.optdesc = optdesc
        self.sc = sc
        self.start_date = start_date
        self.version = version
        
        self.files = files
        
        # Setup download directory
        #   - $HOME/data/mms/
        if data_root is None:
            data_root = os.path.join(os.path.expanduser('~'), 'data', 'mms')
            if not os.path.isdir(data_root):
                os.makedirs(data_root, exist_ok=True)
        
        self.data_root  = data_root
        self._sdc_home  = 'https://lasp.colorado.edu/mms/sdc'
        self._info_type = 'download'
    
    def __str__(self):
        return self.url()
    
    # https://stackoverflow.com/questions/17576009/python-class-property-use-setter-but-evade-getter
    def __setattr__(self, name, value):
        """Control attribute values as they are set."""
        
        # TYPE OF INFO
        #   - Unset other complementary options
        #   - Ensure that at least one of (download | file_names | 
        #     version_info | file_info) are true
        if name == 'anc_product':
            self.data_type = 'ancillary'
        elif name == 'data_type':
            if value not in ('ancillary', 'hk', 'science'):
                raise ValueError('Invalid value for attribute "' + name + '".')
        elif name == 'files':
            if value is not None:
                self.sc = None
                self.instr = None
                self.mode = None
                self.level = None
                self.optdesc = None
                self.version = None
        elif name == 'level':
            if value in [None, 'l2', 'l3']:
                self.site = 'public'
            else:
                self.site = 'private'
        
        # Set the value
        super(MrMMS_SDC_API, self).__setattr__(name, value)
    
    
    def url(self):
        """Build a URL to query the SDC."""
        sep = '/'
        url = sep.join( (self._sdc_home, self.site, 'files', 'api', 'v1', 
                         self._info_type, self.data_type) )
        
        # Build query from parts of file names
        query = '?'
        qdict = self.Query()
        for key in qdict:
            query += key + '=' + qdict[key] + '&'
        
        # Combine URL with query string
        url += query
        return url
    
    def check_response(self, response):
        
        if response.code == 400:
            # Everything is OK
            a = None
        
        elif response.code == 401:
            print('Log-in Required')
        
        else:
            RuntimeError(response.reason)
            
    
    def Download(self):
        self._info_type = 'download'
        # Build the URL sans query
        url = '/'.join((self._sdc_home, self.site, 'files', 'api', 'v1',
                        self._info_type, self.data_type))
        
        # Get available files
        local_files, remote_files = self.Search()
        
        # Get information on the files that were found
        #   - To do that, specify the specific files. This sets all other properties to None
        #   - Save the state of the object as it currently is so that it can be restored
        state = {}
        state['sc'] = self.sc
        state['instr'] = self.instr
        state['mode'] = self.mode
        state['level'] = self.level
        state['optdesc'] = self.optdesc
        state['version'] = self.version
        state['files'] = self.files
        self.files = [file.split('/')[-1] for file in remote_files]
        file_info = self.FileInfo()
        
        # Download each file individually
        for info in file_info['files']:
            # Create the destination directory
            file = self.name2path(info['file_name'])
            if not os.path.isdir(os.path.dirname(file)):
                os.makedirs(os.path.dirname(file))
            
            # downloading: https://stackoverflow.com/questions/16694907/how-to-download-large-file-in-python-with-requests-py
            # progress bar: https://stackoverflow.com/questions/37573483/progress-bar-while-download-file-over-http-with-requests
            try:
                r = requests.post(url,
                                  params={'file': info['file_name']}, 
                                  stream=True)
                with open(file, 'wb') as f:
                    for chunk in tqdm(r.iter_content(chunk_size=1024),
                                      total=info['file_size']/1024,
                                      unit='k',
                                      unit_scale=True):
                        if chunk: # filter out keep-alive new chunks
                            f.write(chunk)
            except:
                if os.path.isfile(file):
                    os.remove(file)
                for key in state:
                    self.files = None
                    setattr(self, key, state[key])
                raise
            
            local_files.append(file)
        
        for key in state:
            self.files = None
            setattr(self, key, state[key])
        
        return local_files
    
    
    def FileInfo(self):
        """Obtain file information from the SDC."""
        self._info_type = 'file_info'
        response = self.Get()
        return response.json()
        
    
    def FileNames(self):
        """Obtain file names from the SDC."""
        self._info_type = 'file_names'
        response = self.Get()
        
        pdb.set_trace()
        
        if response.text == '':
            files = []
        else:
            files = mms_utils.filter_time(response.text.split(','), 
                                          self.start_date, self.end_date)
        
        return files
    
    
    def Local_FileNames(self):
        """Search for MMS files on the local system.
        
        Files must be located in an MMS-like directory structure.
        """
        
        # If no start or end date have been defined,
        #   - Start at beginning of mission
        #   - End at today's date
        start_date = self._start_date
        end_date = self._end_date
        if self._start_date is None:
            start_date = dt.datetime(2015, 9, 1)
        if self._end_date is None:
            end_date = dt.datetime.today()
        
        # Create all dates between start_date and end_date
        deltat = dt.timedelta(days=1)
        dates  = []
        while start_date <= end_date:
            dates.append(start_date.strftime('%Y%m%d'))
            start_date += deltat
        
        # Paths in which to look for files
        #   - Files of all versions and times within interval
        paths = mms_utils.construct_path(self.sc, self.instr, self.mode, self.level,
                                         dates, optdesc=self.optdesc,
                                         root=self.data_root, files=True)
        
        # Search
        result = []
        pwd = os.getcwd()
        for path in paths:
            root = os.path.dirname(path)
            
            try:
                os.chdir(root)
            except FileNotFoundError:
                continue
            except:
                os.chdir(pwd)
                raise
                
            for file in glob.glob(os.path.basename(path)):
                result.append(os.path.join(root, file))

        os.chdir(pwd)
        
        return result
    
    
    def Get(self):
        """Retrieve data from the SDC."""
        # Build the URL sans query
        url = '/'.join((self._sdc_home, self.site, 'files', 'api', 'v1',
                        self._info_type, self.data_type))
        
        # Check on query
        response = requests.post(url, params=self.Query())
        self.check_response(response)
        
        # Return the response for the requested URL
        return response
    
    
    def name2path(self, filename):
        """Convert remote file names to local file name.
        
        Directories of a remote file name are separated by the '/' character,
        as in a web address.
        
        Parameters
        ----------
        filename:  str
                   File name for which the local path is desired.
        
        Returns
        -------
        local_name:  Equivalent local file name. This is the location to
                     which local files are downloaded.
        """
        parts = filename.split('_')
        
        # Burst directories and file names are structured as:
        #   - dirname:  sc/instr/mode/level[/optdesc]/YYYY/MM/DD/
        #   - basename: sc_instr_mode_level[_optdesc]_YYYYMMDDhhmmss_vX.Y.Z.cdf
        # Index from end to catch the optional descriptor, if it exists
        if parts[2] == 'brst':
            path = os.path.join(self.data_root, *parts[0:-2],
                                parts[-2][0:4], parts[-2][4:6],
                                parts[-2][6:8], filename)
        
        # Survey (slow,fast,srvy) directories and file names are structured as:
        #   - dirname:  sc/instr/mode/level[/optdesc]/YYYY/MM/
        #   - basename: sc_instr_mode_level[_optdesc]_YYYYMMDD_vX.Y.Z.cdf
        # Index from end to catch the optional descriptor, if it exists
        else:
            path = os.path.join(self.data_root, *parts[0:-2],
                                parts[-2][0:4], parts[-2][4:6], filename)
        return path
    
    def ParseFileNames(self, filename):
        """Parse file names.
        
        Parse official MMS file names. MMS file names are formatted as
            sc_instr_mode_level[_optdesc]_tstart_vX.Y.Z.cdf
        where
            sc:       spacecraft id
            instr:    instrument id
            mode:     data rate mode
            level:    data level
            optdesc:  optional filename descriptor
            tstart:   start time of file
            vX.Y.Z    file version, with X, Y, and Z version numbers
        
        Params:
        filename (str):  An MMS file name
        
        Returns:
        parts (tuple):  A tuples ordered as
                        (sc, instr, mode, level, optdesc, tstart, version)
                        If opdesc is not present in the file name, the output will
                        contain the empty string ('').
        """
        parts = os.path.basename(filename).split('_')
        
        # If the file does not have an optional descriptor, 
        # put an empty string in its place.
        if len(parts) == 6:
            parts.insert(-2, '')
            
        # Remove the file extension ``.cdf''
        parts[-1] = parts[-1][0:-4]
        return tuple(parts)
    
    
    def Query(self):
        
        # Adjust end date
        #   - The query takes '%Y-%m-%d' but the object allows '%Y-%m-%dT%H:%M:%S'
        #   - Further, the query is half-exclusive: [start, end)
        #   - If the dates are the same but the times are different, then files between
        #     self.start_date and self.end_date will not be found
        #   - In these circumstances, increase the end date by one day
        end_date = self._end_date
        if end_date is not None:
            end_date = self._end_date.strftime('%Y-%m-%d')
            if self._start_date.date() == self._end_date.date():
                end_date = (self._end_date + dt.timedelta(1)).strftime('%Y-%m-%d')
        
        query = {}
        if self.sc is not None:
            query['sc_id'] = self.sc if isinstance(self.sc, str) else ','.join(self.sc)
        if self.instr is not None:
            query['instrument_id'] = self.instr if isinstance(self.instr, str) else ','.join(self.instr)
        if self.mode is not None:
            query['data_rate_mode'] = self.mode if isinstance(self.mode, str) else ','.join(self.mode)
        if self.level is not None:
            query['data_level'] = self.level if isinstance(self.level, str) else ','.join(self.level)
        if self.optdesc is not None:
            query['descriptor'] = self.optdesc if isinstance(self.optdesc, str) else ','.join(self.optdesc)
        if self.version is not None:
            query['version'] = self.version if isinstance(self.version, str) else ','.join(self.version)
        if self.files is not None:
            query['files'] = self.files if isinstance(self.files, str) else ','.join(self.files)
        if self.start_date is not None:
            query['start_date'] = self._start_date.strftime('%Y-%m-%d')
        if self.end_date is not None:
            query['end_date'] = end_date
        
        return query
    
    
    def remote2localnames(self, remote_names):
        """Convert remote file names to local file names.
        
        Directories of a remote file name are separated by the '/' character,
        as in a web address.
        
        Parameters:
        remote_names (list): Remote file names returned by FileNames.
        
        Returns:
        local_names (list):  Equivalent local file name. This is the location to
                             which local files are downloaded.
        """
        # os.path.join() requires string arguments, but str.split() return list.
        #   - Unpack with *: https://docs.python.org/2/tutorial/controlflow.html#unpacking-argument-lists
        local_names =list()
        for file in remote_names:
            local_names.append(os.path.join(self.data_root, *file.split('/')[2:]))
        
        if (len(remote_names) == 1) & (type(remote_names) == 'str'):
            local_names = local_names[0]
        
        return local_names
    
    
    def Search(self):
        """Search for files locally and at the SDC.
        
        TODO:
            Filter results in self.Local_FileNames() by time and remove the time
            filters here. self.FileNames() already filters by time.
        
        Returns:
        files (tuple):  Local and remote files within the interval, returned as
                        (local, remote), where `local` and `remote` are lists.
        """
        
        # Search locally if offline
        if self.offline:
            local_files = self.Local_FileNames
        
        # Search remote first
        #   - SDC is definitive source of files
        #   - Returns most recent version
        else:
            remote_files = self.FileNames()
            
            # Search for the equivalent local file names
            local_files = self.remote2localnames(remote_files)
            idx = [i for i, local in enumerate(local_files) if os.path.isfile(local)]
            
            # Filter based on location
            local_files = [local_files[i] for i in idx]
            remote_files = [remote_files[i] for i in range(len(remote_files)) if i not in idx]
        
        # Filter based on time interval
        if len(local_files) > 0:
            local_files = mms_utils.filter_time(local_files, self.start_date, self.end_date)
        if len(remote_files) > 0:
            remote_files = mms_utils.filter_time(remote_files, self.start_date, self.end_date)
        
        return (local_files, remote_files)
    
    
    def VersionInfo(self):
        """Obtain version information from the SDC."""
        self._info_type = 'version_info'
        response = self.Get()
        return response.json()
    
    
    @property
    def site(self):
        return self._site
    
    @site.setter
    def site(self, value):
        if (value == 'team') | (value == 'team_site') | (value == 'sitl') | (value == 'private'):
            self._site = 'sitl'
        elif (value == 'public') | (value == 'public_site'):
            self._site = 'public'
        else:
            raise ValueError('Invalid value for the "site" attribute')
    
    @property
    def start_date(self):
        return self._start_date.isoformat()
    
    @start_date.setter
    def start_date(self, value):
        # Convert string to datetime object
        if isinstance(value, str):
            try:
                value = dt.datetime.strptime(value, '%Y-%m-%dT%H:%M:%S')
            except:
                try:
                    value = dt.datetime.strptime(value, '%Y-%m-%d')
                except:
                    ValueError('Invalid format for attribute start_date.')
        
        self._start_date = value
    
    
    @property
    def end_date(self):
        return self._end_date.isoformat()
    
    @end_date.setter
    def end_date(self, value):
        # Convert string to datetime object
        if isinstance(value, str):
            try:
                value = dt.datetime.strptime(value, '%Y-%m-%dT%H:%M:%S')
            except:
                try:
                    value = dt.datetime.strptime(value, '%Y-%m-%d')
                except:
                    ValueError('Invalid format for attribute start_date.')
        
        self._end_date = value