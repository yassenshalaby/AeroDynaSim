( function () {

	class STLLoader extends THREE.Loader {

		constructor( manager ) {

			super( manager );

		}

		load( url, onLoad, onProgress, onError ) {

			const scope = this;
			const loader = new THREE.FileLoader( this.manager );
			loader.setPath( this.path );
			loader.setResponseType( 'arraybuffer' );
			loader.setRequestHeader( this.requestHeader );
			loader.setWithCredentials( this.withCredentials );
			loader.load( url, function ( text ) {

				try {

					onLoad( scope.parse( text ) );

				} catch ( e ) {

					if ( onError ) {

						onError( e );

					} else {

						console.error( e );

					}

					scope.manager.itemError( url );

				}

			}, onProgress, onError );

		}

		parse( data ) {

			function isBinary( data ) {

				const reader = new DataView( data );
				const face_size = 32 / 8 * 3 + 32 / 8 * 3 * 3 + 16 / 8;
				const n_faces = reader.getUint32( 80, true );
				const expect = 80 + 32 / 8 + n_faces * face_size;

				if ( expect === reader.byteLength ) {

					return true;

				}

				// some binaries might haveheader filled with garbage, check for ASCII

				const solid = [ 115, 111, 108, 105, 100 ];

				for ( let off = 0; off < 5; off ++ ) {

					for ( let i = 0; i < 5; i ++ ) {

						if ( reader.getUint8( off + i ) !== solid[ i ] ) return true;

					}

				}

				return false;

			}

			function parseBinary( data ) {

				const reader = new DataView( data );
				let faces = reader.getUint32( 80, true );
				
				// Security check: if the file is truncated, clamp the number of faces
				const maxFaces = Math.floor( ( reader.byteLength - 84 ) / 50 );
				if ( faces > maxFaces ) {
					console.warn( 'STLLoader: File is truncated or malformed. Expected ' + faces + ' faces, but found space for only ' + maxFaces + ' faces.' );
					faces = maxFaces;
				}

				let r, g, b, hasColors = false;
				let colors;

				for ( let index = 0; index < 80 - 10; index ++ ) {

					if ( reader.getUint32( index, false ) == 0x434F4C4F && reader.getUint8( index + 4 ) == 0x52 && reader.getUint8( index + 5 ) == 0x3D ) {

						hasColors = true;
						colors = new Float32Array( faces * 3 * 3 );
						r = reader.getUint8( index + 6 ) / 255;
						g = reader.getUint8( index + 7 ) / 255;
						b = reader.getUint8( index + 8 ) / 255;

					}

				}

				const dataOffset = 84;
				const faceLength = 12 * 4 + 2;
				const geometry = new THREE.BufferGeometry();
				const vertices = new Float32Array( faces * 3 * 3 );
				const normals = new Float32Array( faces * 3 * 3 );

				for ( let f = 0; f < faces; f ++ ) {

					const start = dataOffset + f * faceLength;
					const nx = reader.getFloat32( start, true );
					const ny = reader.getFloat32( start + 4, true );
					const nz = reader.getFloat32( start + 8, true );

					for ( let i = 0; i < 3; i ++ ) {

						const vertexstart = start + 12 + i * 12;
						vertices[ f * 9 + i * 3 ] = reader.getFloat32( vertexstart, true );
						vertices[ f * 9 + i * 3 + 1 ] = reader.getFloat32( vertexstart + 4, true );
						vertices[ f * 9 + i * 3 + 2 ] = reader.getFloat32( vertexstart + 8, true );
						normals[ f * 9 + i * 3 ] = nx;
						normals[ f * 9 + i * 3 + 1 ] = ny;
						normals[ f * 9 + i * 3 + 2 ] = nz;

						if ( hasColors ) {

							colors[ f * 9 + i * 3 ] = r;
							colors[ f * 9 + i * 3 + 1 ] = g;
							colors[ f * 9 + i * 3 + 2 ] = b;

						}

					}

				}

				geometry.setAttribute( 'position', new THREE.BufferAttribute( vertices, 3 ) );
				geometry.setAttribute( 'normal', new THREE.BufferAttribute( normals, 3 ) );

				if ( hasColors ) {

					geometry.setAttribute( 'color', new THREE.BufferAttribute( colors, 3 ) );
					geometry.hasColors = true;
					geometry.alpha = reader.getUint8( index + 9 ) / 255;

				}

				return geometry;

			}

			function parseASCII( data ) {

				const geometry = new THREE.BufferGeometry();
				const patternSolid = /solid([\s\S]*?)endsolid/g;
				const patternFace = /facet[\s\S]*?normal[\s\S]*?vertex[\s\S]*?vertex[\s\S]*?vertex[\s\S]*?endfacet/g;
				let faceCounter = 0;
				const patternFloat = /[\s]+([+-]?\d*\.?\d+(?:[eE][+-]?\d+)?)/g;
				const vertices = [];
				const normals = [];
				const text = THREE.LoaderUtils.decodeText( data );
				let result;

				while ( ( result = patternSolid.exec( text ) ) !== null ) {

					const solid = result[ 0 ];
					let result2;

					while ( ( result2 = patternFace.exec( solid ) ) !== null ) {

						const face = result2[ 0 ];
						let nx = 0,
							ny = 0,
							nz = 0;
						let result3;
						let vertexCounter = 0;

						while ( ( result3 = patternFloat.exec( face ) ) !== null ) {

							if ( vertexCounter < 3 ) {

								nx = parseFloat( result3[ 1 ] );
								ny = parseFloat( result3[ 2 ] );
								nz = parseFloat( result3[ 3 ] );
								vertexCounter = 3;

							} else {

								vertices.push( parseFloat( result3[ 1 ] ) );
								vertexCounter ++;
								normals.push( nx, ny, nz );

							}

						}

						faceCounter ++;

					}

				}

				geometry.setAttribute( 'position', new THREE.Float32BufferAttribute( vertices, 3 ) );
				geometry.setAttribute( 'normal', new THREE.Float32BufferAttribute( normals, 3 ) );
				return geometry;

			}

			function ensureString( buffer ) {

				if ( typeof buffer !== 'string' ) {

					return THREE.LoaderUtils.decodeText( new Uint8Array( buffer ) );

				}

				return buffer;

			}

			function ensureBinary( buffer ) {

				if ( typeof buffer === 'string' ) {

					const array_buffer = new Uint8Array( buffer.length );

					for ( let i = 0; i < buffer.length; i ++ ) {

						array_buffer[ i ] = buffer.charCodeAt( i ) & 0xff; // top byte is not actually used for the 'real' ASCII

					}

					return array_buffer.buffer;

				}

				return buffer;

			}

			const binData = ensureBinary( data );
			return isBinary( binData ) ? parseBinary( binData ) : parseASCII( binData );

		}

	}

	THREE.STLLoader = STLLoader;

} )();
