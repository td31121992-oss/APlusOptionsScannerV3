"""Short company profiles for the F&O stocks, shown on the Stock Analysis page.

SYMBOL | company | what it does | owner / promoter | founded.
Compiled from general knowledge (as of about 2025-26). Ownership and stakes change, so treat the owner field as
indicative and verify before relying on it. "~" means approximate. Informational only.
"""

from __future__ import annotations

_RAW = """
360ONE|360 ONE WAM|Wealth and asset management (ex IIFL Wealth)|Karan Bhagat and founding team|2008
ABB|ABB India|Power and automation equipment|ABB Ltd, Switzerland|1949
ABCAPITAL|Aditya Birla Capital|NBFC, insurance and asset management|Aditya Birla Group (Kumar Mangalam Birla)|2007
ADANIENSOL|Adani Energy Solutions|Power transmission and distribution|Adani family (Gautam Adani)|2013
ADANIENT|Adani Enterprises|Group flagship: airports, mining, new-energy incubator|Adani family (Gautam Adani)|1993
ADANIGREEN|Adani Green Energy|Renewable power (solar, wind)|Adani family; TotalEnergies holds a stake|2015
ADANIPORTS|Adani Ports and SEZ|Ports and logistics|Adani family (Gautam Adani)|1998
ADANIPOWER|Adani Power|Thermal power generation|Adani family (Gautam Adani)|1996
ALKEM|Alkem Laboratories|Pharmaceuticals|Singh family (Samprada Singh)|1973
AMBER|Amber Enterprises|Room ACs and electronics manufacturing|Jasbir Singh and family|1990
AMBUJACEM|Ambuja Cements|Cement|Adani Group (acquired 2022)|1983
ANANDRATHI|Anand Rathi Wealth|Wealth management|Anand Rathi family|~1995
ANGELONE|Angel One|Stockbroking and fintech|Dinesh Thakkar and family|1987
APLAPOLLO|APL Apollo Tubes|Structural steel tubes|Sanjay Gupta (Apollo group)|1986
APOLLOHOSP|Apollo Hospitals|Hospitals and healthcare|Reddy family (Dr Prathap C. Reddy)|1983
ASHOKLEY|Ashok Leyland|Commercial vehicles|Hinduja Group|1948
ASIANPAINT|Asian Paints|Paints and coatings|Choksey, Dani, Vakil and Muljiani families|1942
ASTRAL|Astral|Plastic pipes and adhesives|Sandeep Engineer and family|1996
ATHERENERG|Ather Energy|Electric scooters|Founders Tarun Mehta and Swapnil Jain; Hero MotoCorp is a major investor|2013
AUBANK|AU Small Finance Bank|Small finance bank|Sanjay Agarwal (founder)|1996 (bank 2017)
AUROPHARMA|Aurobindo Pharma|Generic pharmaceuticals|P.V. Ramaprasad Reddy and K. Nityananda Reddy|1986
AXISBANK|Axis Bank|Private bank|Widely held (institutions such as LIC), no single promoter|1993
BAJAJ-AUTO|Bajaj Auto|Motorcycles and three-wheelers|Bajaj family (Rajiv and Sanjiv Bajaj)|1945
BAJAJFINSV|Bajaj Finserv|Financial services holding company|Bajaj family|2007
BAJAJHLDNG|Bajaj Holdings and Investment|Investment holding company|Bajaj family|1945
BAJFINANCE|Bajaj Finance|NBFC (consumer and business loans)|Bajaj Finserv (about 52%)|1987
BANDHANBNK|Bandhan Bank|Private bank|Bandhan Financial Holdings (Chandra Shekhar Ghosh)|2015 (microfinance 2001)
BANKBARODA|Bank of Baroda|Public-sector bank|Government of India|1908
BANKINDIA|Bank of India|Public-sector bank|Government of India|1906
BDL|Bharat Dynamics|Missiles and defence systems|Government of India|1970
BEL|Bharat Electronics|Defence and professional electronics|Government of India|1954
BHARATFORG|Bharat Forge|Forgings and auto components|Kalyani Group (Baba Kalyani)|1961
BHARTIARTL|Bharti Airtel|Telecom|Bharti family (Sunil Mittal) with Singtel|1995
BHEL|Bharat Heavy Electricals|Power and industrial equipment|Government of India|1964
BIOCON|Biocon|Biopharmaceuticals|Kiran Mazumdar-Shaw|1978
BLUESTARCO|Blue Star|Air conditioning and refrigeration|Advani family|1943
BOSCHLTD|Bosch Ltd|Auto parts and technology|Robert Bosch GmbH, Germany|1951
BPCL|Bharat Petroleum|Oil refining and fuel marketing|Government of India|1952
BRITANNIA|Britannia Industries|Biscuits and bakery foods|Wadia group (Nusli Wadia)|1892
BSE|BSE Ltd|Stock exchange|Widely held, no promoter|1875
CAMS|Computer Age Management Services|Mutual-fund registrar and transfer agent|Professionally managed|1988
CANBK|Canara Bank|Public-sector bank|Government of India|1906
CDSL|Central Depository Services|Securities depository|BSE Ltd is the largest holder|1999
CGPOWER|CG Power and Industrial Solutions|Power and industrial equipment|Murugappa Group|1937
CHOLAFIN|Cholamandalam Investment and Finance|NBFC (vehicle finance)|Murugappa Group|1978
CIPLA|Cipla|Pharmaceuticals|Hamied family|1935
COALINDIA|Coal India|Coal mining|Government of India|1975
COCHINSHIP|Cochin Shipyard|Shipbuilding and ship repair|Government of India|1972
COFORGE|Coforge|IT services|Professionally managed (formerly NIIT Technologies)|1990
COLPAL|Colgate-Palmolive India|Oral care|Colgate-Palmolive, USA|1937
CONCOR|Container Corporation of India|Rail container logistics|Government of India|1988
CROMPTON|Crompton Greaves Consumer Electricals|Fans, lighting and appliances|Professionally managed, no promoter|2015 (brand 1937)
CUMMINSIND|Cummins India|Engines and power generators|Cummins Inc, USA|1962
DABUR|Dabur India|FMCG and ayurvedic products|Burman family|1884
DELHIVERY|Delhivery|Logistics and supply chain|Founders (Sahil Barua and others) with SoftBank and other investors|2011
DIVISLAB|Divi's Laboratories|Pharma ingredients (APIs)|Murali K. Divi and family|1990
DIXON|Dixon Technologies|Electronics manufacturing services|Sunil Vachani and family|1993
DLF|DLF|Real estate developer|Singh family (K.P. Singh, Rajiv Singh)|1946
DMART|Avenue Supermarts (DMart)|Supermarket retail|Radhakishan Damani and family|2000
DRREDDY|Dr. Reddy's Laboratories|Pharmaceuticals|Reddy family|1984
EICHERMOT|Eicher Motors|Royal Enfield motorcycles|Lal family (Siddhartha Lal)|1948
ENRIN|Siemens Energy India|Power and grid equipment|Siemens Energy AG, Germany|2024-25 (demerged from Siemens Ltd)
ETERNAL|Eternal (formerly Zomato)|Food delivery and Blinkit quick commerce|Professionally managed; founder Deepinder Goyal|2008
FEDERALBNK|Federal Bank|Private bank|Widely held, no promoter|1931
FORCEMOT|Force Motors|Commercial vehicles|Firodia family|1958
FORTIS|Fortis Healthcare|Hospitals|IHH Healthcare, Malaysia|1996
GAIL|GAIL (India)|Natural gas pipelines and distribution|Government of India|1984
GLENMARK|Glenmark Pharmaceuticals|Pharmaceuticals|Saldanha family (Glenn Saldanha)|1977
GMRAIRPORT|GMR Airports|Airports (Delhi, Hyderabad and others)|GMR Group (G.M. Rao)|1996
GODFRYPHLP|Godfrey Phillips India|Tobacco and FMCG|Modi family (K.K. Modi group)|1936
GODREJCP|Godrej Consumer Products|FMCG (personal and home care)|Godrej family|2000
GODREJPROP|Godrej Properties|Real estate developer|Godrej family|1985
GVT&D|GE Vernova T&D India|Power transmission equipment|GE Vernova, USA|1957
HAL|Hindustan Aeronautics|Aircraft and helicopters|Government of India|1940
HAVELLS|Havells India|Electricals and consumer durables|Gupta family (Qimat Rai Gupta)|1958
HCLTECH|HCL Technologies|IT services|Shiv Nadar|1976
HDFCAMC|HDFC Asset Management|Mutual funds|HDFC Bank (after merger) and abrdn|1999
HDFCBANK|HDFC Bank|Private bank|Widely held, no promoter after the HDFC merger|1994
HDFCLIFE|HDFC Life Insurance|Life insurance|HDFC Bank group|2000
HEROMOTOCO|Hero MotoCorp|Two-wheelers|Munjal family|1984
HINDALCO|Hindalco Industries|Aluminium and copper (owns Novelis)|Aditya Birla Group|1958
HINDPETRO|Hindustan Petroleum|Oil refining and fuel marketing|Government of India (through ONGC)|1952
GRASIM|Grasim Industries|Cement (through UltraTech), viscose and chemicals|Aditya Birla Group|1947
HINDUNILVR|Hindustan Unilever|FMCG|Unilever, UK|1933
HINDZINC|Hindustan Zinc|Zinc and silver mining|Vedanta (Anil Agarwal); Government of India holds a minority|1966
HYUNDAI|Hyundai Motor India|Passenger cars|Hyundai Motor Company, South Korea|1996
ICICIBANK|ICICI Bank|Private bank|Widely held, no promoter|1994
ICICIGI|ICICI Lombard General Insurance|General insurance|ICICI Bank and Fairfax (earlier)|2001
ICICIPRULI|ICICI Prudential Life Insurance|Life insurance|ICICI Bank and Prudential plc|2000
IDEA|Vodafone Idea|Telecom|Vodafone Group, Aditya Birla Group; Government of India holds a stake|1995 (merger 2018)
IDFCFIRSTB|IDFC First Bank|Private bank|Widely held, no promoter|2015 (bank)
IEX|Indian Energy Exchange|Electricity trading exchange|Widely held|2008
INDHOTEL|Indian Hotels Company (Taj)|Hotels|Tata Group|1899
INDIANB|Indian Bank|Public-sector bank|Government of India|1907
INDIGO|InterGlobe Aviation (IndiGo)|Airline|Rahul Bhatia and Gangwal family|2006
INDUSINDBK|IndusInd Bank|Private bank|Hinduja group (promoters)|1994
INDUSTOWER|Indus Towers|Telecom towers|Bharti Airtel and Vodafone Group|2007
INFY|Infosys|IT services|Founders (N.R. Narayana Murthy and others); widely held|1981
INOXWIND|Inox Wind|Wind turbines|Jain family (Inox group)|2009
IOC|Indian Oil Corporation|Oil refining and fuel marketing|Government of India|1959
IREDA|Indian Renewable Energy Development Agency|Renewable-energy financing|Government of India|1987
IRFC|Indian Railway Finance Corporation|Railway financing|Government of India|1986
ITC|ITC|FMCG, hotels, agriculture, paper|Widely held; British American Tobacco is the largest holder|1910
JINDALSTEL|Jindal Steel and Power|Steel and power|Jindal family (Naveen Jindal)|1979
JIOFIN|Jio Financial Services|Financial services|Reliance Industries (Mukesh Ambani)|2023 (demerged from Reliance)
JSWENERGY|JSW Energy|Power generation|JSW Group (Sajjan Jindal)|1994
JSWSTEEL|JSW Steel|Steel|JSW Group (Sajjan Jindal)|1982
JUBLFOOD|Jubilant FoodWorks|Domino's Pizza operator|Bhartia and Jubilant group|1995
KALYANKJIL|Kalyan Jewellers|Jewellery retail|T.S. Kalyanaraman and family|1993
KAYNES|Kaynes Technology|Electronics manufacturing|Ramesh Kannan|2008
KEI|KEI Industries|Cables and wires|Gupta family|1968
KFINTECH|KFin Technologies|Mutual-fund registrar and issuer services|Professionally managed|2017
KOTAKBANK|Kotak Mahindra Bank|Private bank|Uday Kotak (promoter)|1985 (bank 2003)
KPITTECH|KPIT Technologies|Automotive software|Founders Kishor Patil and Ravi Pandit|1990
LAURUSLABS|Laurus Labs|Pharma ingredients (APIs)|Dr Satyanarayana Chava|2005
LICHSGFIN|LIC Housing Finance|Housing finance|Life Insurance Corporation (Government of India)|1989
LICI|Life Insurance Corporation of India|Life insurance|Government of India|1956
LODHA|Macrotech Developers (Lodha)|Real estate developer|Lodha family (Mangal Prabhat Lodha)|1995
LT|Larsen and Toubro|Engineering and construction|Widely held, no promoter|1938
LTF|L&T Finance|NBFC|Larsen and Toubro (about 66%)|2008
LTM|LTIMindtree|IT services|Larsen and Toubro|1996 (Mindtree 1999 and L&T Infotech 1997 merged in 2022)
LUPIN|Lupin|Pharmaceuticals|Gupta family (Desh Bandhu Gupta, Nilesh Gupta)|1968
M&M|Mahindra and Mahindra|SUVs, tractors and farm equipment|Mahindra family (Anand Mahindra)|1945
MAHABANK|Bank of Maharashtra|Public-sector bank|Government of India|1935
MANAPPURAM|Manappuram Finance|Gold loans|V.P. Nandakumar|1992
MANKIND|Mankind Pharma|Pharmaceuticals|Juneja family (Ramesh and Rajeev Juneja)|1995
MARICO|Marico|FMCG (Parachute, Saffola)|Harsh Mariwala and family|1990
MARUTI|Maruti Suzuki India|Passenger cars|Suzuki Motor Corporation, Japan|1981
MAXHEALTH|Max Healthcare Institute|Hospitals|Professionally managed|2001
MAZDOCK|Mazagon Dock Shipbuilders|Warships and submarines|Government of India|1934 (origins 1774)
MCX|Multi Commodity Exchange|Commodity exchange|Widely held, no promoter|2003
MFSL|Max Financial Services|Life insurance holding (Max Life)|Max group (Analjit Singh) and Axis group|-
MOTHERSON|Samvardhana Motherson International|Auto components|Sehgal family (Vivek Chaand Sehgal)|1975
MOTILALOFS|Motilal Oswal Financial Services|Broking, wealth and asset management|Motilal Oswal and Raamdeo Agrawal|1987
MPHASIS|Mphasis|IT services|Blackstone|1998
MUTHOOTFIN|Muthoot Finance|Gold loans|Muthoot family|1997 (group 1939)
NAM-INDIA|Nippon Life India Asset Management|Mutual funds|Nippon Life Insurance, Japan|1995
NATIONALUM|National Aluminium Company (NALCO)|Aluminium|Government of India|1981
NAUKRI|Info Edge (Naukri.com)|Online classifieds and jobs|Sanjeev Bikhchandani|1995
NBCC|NBCC (India)|Construction and project management|Government of India|1960
NESTLEIND|Nestle India|Food and beverages|Nestle S.A., Switzerland|1959
NHPC|NHPC|Hydroelectric power|Government of India|1975
NMDC|NMDC|Iron ore mining|Government of India|1958
NTPC|NTPC|Power generation|Government of India|1975
NYKAA|FSN E-Commerce Ventures (Nykaa)|Beauty and fashion e-commerce|Falguni Nayar and family|2012
OBEROIRLTY|Oberoi Realty|Real estate developer|Vikas Oberoi|1998
OFSS|Oracle Financial Services Software|Banking software|Oracle Corporation, USA|1992
OIL|Oil India|Oil and gas exploration|Government of India|1959
ONGC|Oil and Natural Gas Corporation|Oil and gas exploration|Government of India|1956
PAGEIND|Page Industries (Jockey India)|Innerwear and apparel|Genomal family|1994
PATANJALI|Patanjali Foods (formerly Ruchi Soya)|FMCG and edible oils|Baba Ramdev and Acharya Balkrishna group|1986
PAYTM|One 97 Communications (Paytm)|Payments and fintech|Vijay Shekhar Sharma|2000
PERSISTENT|Persistent Systems|IT services|Anand Deshpande and family|1990
PETRONET|Petronet LNG|LNG import terminals|ONGC, IOC, GAIL, BPCL (government companies)|1998
PFC|Power Finance Corporation|Power-sector financing|Government of India|1986
PGEL|PG Electroplast|Electronics manufacturing|Gupta family|1972
PHOENIXLTD|Phoenix Mills|Malls and real estate|Ruia family|1905
PIDILITIND|Pidilite Industries|Adhesives (Fevicol)|Parekh family|1959
PIIND|PI Industries|Agrochemicals|Mehra family (Salil Singhal)|1946
PNB|Punjab National Bank|Public-sector bank|Government of India|1894
PNBHOUSING|PNB Housing Finance|Housing finance|Punjab National Bank and Carlyle|1988
POLICYBZR|PB Fintech (PolicyBazaar)|Online insurance marketplace|Yashish Dahiya and Alok Bansal (founders)|2008
POLYCAB|Polycab India|Cables and wires|Jaisinghani family|1996
POWERGRID|Power Grid Corporation|Power transmission|Government of India|1989
POWERINDIA|Hitachi Energy India|Power technologies|Hitachi Energy, Japan|1949
PREMIERENE|Premier Energies|Solar cells and modules|Chiranjeevi Saluja and family|1995
PRESTIGE|Prestige Estates|Real estate developer|Razack family (Irfan Razack)|1986
RADICO|Radico Khaitan|Alcohol (Magic Moments, 8PM)|Khaitan family (Lalit Khaitan)|1943
RBLBANK|RBL Bank|Private bank|Widely held; Emirates NBD has been taking a controlling stake|1943
RECLTD|REC Limited|Power-sector financing|Government of India (through PFC)|1969
RELIANCE|Reliance Industries|Energy, retail and telecom (Jio)|Mukesh Ambani and family|1957 (listed company 1973)
RVNL|Rail Vikas Nigam|Railway infrastructure|Government of India|2003
SAGILITY|Sagility|Healthcare business-process services|Professionally managed (Bain Capital)|~2002
SAIL|Steel Authority of India|Steel|Government of India|1973
SBICARD|SBI Cards and Payment Services|Credit cards|State Bank of India (about 69%)|1998
SBILIFE|SBI Life Insurance|Life insurance|State Bank of India and BNP Paribas Cardif|2000
SBIN|State Bank of India|Public-sector bank|Government of India|1955 (roots 1806)
SHREECEM|Shree Cement|Cement|Bangur family|1979
SHRIRAMFIN|Shriram Finance|NBFC (vehicle loans)|Shriram Group|1979
SIEMENS|Siemens Ltd (India)|Industrial and infrastructure technology|Siemens AG, Germany|1957
SOLARINDS|Solar Industries India|Industrial explosives|Nuwal family (Satyanarayan Nuwal)|1995
SONACOMS|Sona BLW Precision Forgings|Auto components|Kapur family (Sona group)|1995
SRF|SRF|Chemicals and technical textiles|Bharat Ram family|1970
SUNPHARMA|Sun Pharmaceutical|Pharmaceuticals|Dilip Shanghvi and family|1983
SUPREMEIND|Supreme Industries|Plastic pipes and products|Taparia family|1942
SUZLON|Suzlon Energy|Wind turbines|Tulsi Tanti family|1995
SWIGGY|Swiggy|Food delivery and Instamart|Professionally managed; founders Sriharsha Majety and Nandan Reddy|2014
TATACONSUM|Tata Consumer Products|Tea, salt and packaged foods|Tata Group|1962
TATAELXSI|Tata Elxsi|Design and engineering services|Tata Group|1989
TATAPOWER|Tata Power|Power generation and distribution|Tata Group|1919
TATASTEEL|Tata Steel|Steel|Tata Group|1907
TCS|Tata Consultancy Services|IT services|Tata Group (Tata Sons)|1968
TECHM|Tech Mahindra|IT services|Mahindra Group|1986
TIINDIA|Tube Investments of India|Engineering, bicycles and EVs|Murugappa Group|1949
TITAN|Titan Company|Watches and jewellery|Tata Group and Tamil Nadu government (TIDCO)|1984
TMPV|Tata Motors Passenger Vehicles|Cars (Tata, Jaguar Land Rover)|Tata Group|1945 (listed as a separate entity after the 2025 demerger)
TORNTPHARM|Torrent Pharmaceuticals|Pharmaceuticals|Mehta family (Torrent Group)|1972
TRENT|Trent (Westside, Zudio)|Retail|Tata Group|1952
TVSMOTOR|TVS Motor Company|Two-wheelers|Venu Srinivasan and TVS family|1978
UJJIVANSFB|Ujjivan Small Finance Bank|Small finance bank|Widely held (earlier promoter Ujjivan Financial Services)|2017 (microfinance 2005)
ULTRACEMCO|UltraTech Cement|Cement|Aditya Birla Group|1983
UNIONBANK|Union Bank of India|Public-sector bank|Government of India|1919
UNITDSPR|United Spirits|Alcohol (McDowell's, Royal Challenge)|Diageo, UK|-
UNOMINDA|Uno Minda|Auto components|Minda family (Ashok Minda)|1958
UPL|UPL|Agrochemicals|Shroff family (Jai and Vikram Shroff)|1969
VBL|Varun Beverages|PepsiCo bottler and distributor|Jaipuria family (RJ Corp)|1995
VEDL|Vedanta|Mining and metals|Anil Agarwal (through Volcan Investments)|1976
VMM|Vishal Mega Mart|Value retail|Samayat Services (Kedaara Capital)|2001
VOLTAS|Voltas|Air conditioning and engineering projects|Tata Group|1954
WAAREEENER|Waaree Energies|Solar modules|Doshi family (Hitesh Doshi)|2007
WIPRO|Wipro|IT services|Azim Premji family|1945
YESBANK|Yes Bank|Private bank|SBI-led group and SMBC, Japan|2004
ZYDUSLIFE|Zydus Lifesciences|Pharmaceuticals|Patel family (Pankaj Patel)|1952
"""

PROFILES: dict[str, dict[str, str]] = {}
for _line in _RAW.strip().splitlines():
    _p = [x.strip() for x in _line.split("|")]
    if len(_p) == 5:
        PROFILES[_p[0].upper()] = {"name": _p[1], "business": _p[2], "owner": _p[3], "founded": _p[4]}

NOTE = "Short profile from general knowledge (about 2025-26); ownership changes, so verify before relying on it."


def get(symbol: str) -> dict[str, str] | None:
    p = PROFILES.get(str(symbol or "").strip().upper())
    return {**p, "note": NOTE} if p else None
