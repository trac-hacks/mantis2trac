# mantis2trac #

Mantis bugs can be imported into Trac using this script.

Currently, the following data is imported from Mantis:
  * bugs
  * bug comments
  * bug activity (field changes)
  * attachments

If you use the script, please read the NOTES section (at the top of the file) and make sure you adjust the config parameters for your environment.

## Bugs/Feature Requests ##

Please report any problems in the [issues section](https://github.com/trac-hacks/mantis2trac/issues).
Historical bugs and feature requests are on [trac-hacks.org](http://trac-hacks.org/report/9?COMPONENT=MantisImportScript).

## Example ##

mantis2trac.py has similar parameters as the bugzilla2trac.py script:

mantis2trac - Imports a bug database from Mantis into Trac.

Usage: mantis2trac.py [options] 

Available Options:
```
  --db [MySQL dbname]                - Mantis database
  --tracenv /path/to/trac/env        - Full path to Trac db environment
  -h | --host [MySQL hostname]       - Mantis DNS host name
  -u | --user [MySQL username]       - Effective Mantis database user
  -p | --passwd [MySQL password]     - Mantis database user password
  -c | --clean                       - Remove current Trac tickets before importing
  --products [Product1,"Product 2"]  - List of products to import from mantis
  --help | help                      - This help info
```

## Author/Contributors ##

### Original Author: ###
[Paul Baranowski](http://paulbaranowski.org/)

### Contributors: ###
 * [João Prado Maia](http://pessoal.org/)
 * [Anton Stroganov](http://github.com/Aeon)
 * [John Lichovník](http://ufo.cz)
 * [Matthew Parmelee](http://interworx.com)
 * [Steffen Mecke](https://github.com/stm2)
